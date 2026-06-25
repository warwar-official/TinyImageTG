import httpx

LLAMA_CPP_URL = "http://127.0.0.1:8080/v1/chat/completions"
COMFYUI_BASE_URL = "http://127.0.0.1:8188"

async def request_llama_cpp(system_prompt:str, prompt:str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url=LLAMA_CPP_URL,
                json={
                    "messages":[
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "max_tokens": 1024
                },
                timeout=60.0
            )
            if r.status_code != 200:
                return {"error": f"Unexpected status code {r.status_code}: {r.text}"}
            data = r.json()
            text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            if not text:
                return {"error": "Empty response from LLM"}
            return {"message": text}
    except Exception as e:
        return {"error": f"HTTP request failed: {str(e)}"}

async def comfyui_send_prompt(workflow: dict):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url=f"{COMFYUI_BASE_URL}/prompt",
                json={"prompt": workflow},
                timeout=30.0
            )
            if r.status_code != 200:
                return {"error": f"Unexpected status code {r.status_code}: {r.text}"}
            data = r.json()
            return {"prompt_id": data.get("prompt_id")}
    except Exception as e:
        return {"error": f"HTTP request failed: {str(e)}"}

async def comfyui_check_status(prompt_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url=f"{COMFYUI_BASE_URL}/history/{prompt_id}",
                timeout=30.0
            )
            if r.status_code != 200:
                return {"completed": False, "error": f"Unexpected status code {r.status_code}: {r.text}"}
            data = r.json()
            if not data or prompt_id not in data:
                return {"completed": False}
            
            history_data = data[prompt_id]
            outputs = history_data.get("outputs", {})
            images = []
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img in node_output["images"]:
                        images.append({
                            "filename": img["filename"],
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output")
                        })
            return {"completed": True, "images": images}
    except Exception as e:
        return {"completed": False, "error": f"HTTP request failed: {str(e)}"}

async def comfyui_load_image(filename: str, subfolder: str = "", image_type: str = "output"):
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type
            }
            r = await client.get(
                url=f"{COMFYUI_BASE_URL}/view",
                params=params,
                timeout=30.0
            )
            if r.status_code != 200:
                return {"error": f"Unexpected status code {r.status_code}: {r.text}"}
            return r.content
    except Exception as e:
        return {"error": f"HTTP request failed: {str(e)}"}
    