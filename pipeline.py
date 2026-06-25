import asyncio
import json
import logging
import os
import random
import sys
import time
import yaml

from provider import request_llama_cpp, comfyui_send_prompt, comfyui_check_status, comfyui_load_image

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
base_dir = os.path.abspath(os.path.dirname(__file__))

DEFAULT_WORKFLOW_PATH = os.path.join(base_dir, "data/workflows/")
DEFAULT_PROMPTS_PATH = os.path.join(base_dir, "data/configs/prompts.yaml")
DEFAULT_IMAGE_OUTPUT_DIR = os.path.join(base_dir, "data/images/generated/")

"""
Task signature:
{
    "chat_id": int,
    "message_text": str,
    "image_path": [str]
}
Responce signature:
{
    "error": str or None,
    "message": str or None,
    "image": {"path": str, "real_name": str} or None
}
"""

async def pipeline_worker(queue: asyncio.Queue, callback: callable):
    workflows: dict = load_workflows()
    prompts = load_prompts()
    while True:
        task = await queue.get()
        try:
            chat_id = task.get('chat_id')
            prompt = task.get('message_text')
            image_path = task.get('image_path')
            # Prompt optimisation
            if not "[NO ENCHANCE]" in prompt:
                result = await request_llama_cpp(
                    system_prompt=prompts.get("system_prompt", ""),
                    prompt=prompt)
                if not result.get('error') and result.get('message'):
                    prompt = result.get('message')
                else:
                    logger.exception("LLM prompt optimisation failed: %s", result.get('error'))
                    await callback(chat_id, {"error": result.get('error')})
            else:
                prompt = prompt.replace("[NO ENCHANCE]", "")
            # Image generation
            workflow = insert_prompt(workflows.get("Text-to-Img", {}), prompt, prompts.get("image_negative_prompt", ""))
            if image_path:
                workflow = insert_image(workflow, image_path)
            result = await comfyui_send_prompt(workflow)
            if not result.get('error') and result.get('prompt_id'):
                prompt_id = result.get('prompt_id')
                await callback(chat_id, {"message": f"Generation started. Prompt ID: {prompt_id}"})
                
                completed = False
                max_retries = 300
                for attempt in range(max_retries):
                    status = await comfyui_check_status(prompt_id)
                    if status.get("completed"):
                        completed = True
                        images = status.get("images", [])
                        break
                    time.sleep(2)
                
                if completed and len(images) > 0:
                    img_info = images[0]
                    filename = img_info["filename"]
                    subfolder = img_info.get("subfolder", "")
                    img_type = img_info.get("type", "output")
                    
                    img_bytes = await comfyui_load_image(filename, subfolder, img_type)
                    if isinstance(img_bytes, bytes):
                        os.makedirs(DEFAULT_IMAGE_OUTPUT_DIR, exist_ok=True)
                        output_path = os.path.join(DEFAULT_IMAGE_OUTPUT_DIR, filename)
                        with open(output_path, "wb") as f:
                            f.write(img_bytes)
                        await callback(chat_id, {"image": {"path": output_path, "real_name": filename}})
                    else:
                        await callback(chat_id, {"error": "Failed to load image"})
                else:
                    await callback(chat_id, {"error": "Generation timed out or failed"})
            else:
                logger.exception("ComfyUI prompt sending failed: %s", result.get('error'))
                await callback(chat_id, {"error": result.get('error')})

        except Exception as e:
            await callback(task.get('chat_id'), {"error": str(e)})

def load_prompts() -> dict:
    try:
        if not os.path.exists(DEFAULT_PROMPTS_PATH):
            logger.exception("Prompts file not found")
            return {}
        
        with open(DEFAULT_PROMPTS_PATH, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)
        
        return prompts
    except Exception as e:
        logger.exception("Failed to load prompts: %s", e)
        return {}

def load_workflows() -> dict:
    try:
        if not os.path.exists(DEFAULT_WORKFLOW_PATH):
            logger.exception("Workflows directory not found")
            return {}
        
        workflows = {}
        for filename in os.listdir(DEFAULT_WORKFLOW_PATH):
            if filename.endswith(".json"):
                filepath = os.path.join(DEFAULT_WORKFLOW_PATH, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    workflow = json.load(f)
                    workflows[filename.replace(".json", "")] = workflow
        
        return workflows
    except Exception as e:
        logger.exception("Failed to load workflows: %s", e)
        return {}

def insert_prompt(workflow: dict, prompt: str, neg_prompt: str = "") -> dict:
    try:
        for node in workflow.values():
            if node.get("_meta", {}).get("title") == "Prompt":
                node["inputs"]["value"] = prompt
            if node.get("_meta", {}).get("title") == "NegPrompt":
                node["inputs"]["value"] = neg_prompt
            if node.get("_meta", {}).get("title") == "Seed":
                node["inputs"]["value"] = random.randint(0, 2**32 - 1)
        return workflow
    except Exception as e:
        logger.exception("Failed to insert prompt: %s", e)
        return workflow

def insert_image(workflow: dict, image_path: list[str]) -> dict:
    try:
        vae_node = None
        last_prompt_conditioning_node = None
        last_negprompt_conditioning_node = None
        for node in workflow.values():
            if node.get("_meta", {}).get("title") == "VAE Decode":
                vae_node = node["inputs"]["vae"][0]
            if node.get("_meta", {}).get("title") == "KSampler":
                last_prompt_conditioning_node = node["inputs"]["positive"][0]
                last_negprompt_conditioning_node = node["inputs"]["negative"][0]
        # Set reference image latents
        for i, image in enumerate(image_path):
            load_image_node = {
                "inputs": {
                    "image": os.path.join(base_dir, image)
                },
                "class_type": "LoadImage",
                "_meta": {
                    "title": f"LoadImage_{i}"
                }
            }
            upscale_image_node = {
                "inputs": {
                    "upscale_method": "area",
                    "width": 512,
                    "height": 512,
                    "crop": "disabled",
                    "image": [f"{200 + i*100 + 0}", 0]
                },
                "class_type": "ImageScale",
                "_meta": {
                    "title": f"UpscaleImage_{i}"
                }
            }
            vae_encode_node = {
                "inputs": {
                    "pixels": [f"{200 + i*100 + 1}", 0],
                    "vae": [vae_node, 0]
                },
                "class_type": "VAEEncode",
                "_meta": {
                    "title": f"VAEEncode_{i}"
                }
            }
            reference_prompt_latent_node = {
                "inputs": {
                    "conditioning": [last_prompt_conditioning_node, 0],
                    "latent": [f"{200 + i*100 + 2}", 0]
                },
                "class_type": "ReferenceLatent",
                "_meta": {
                    "title": f"ReferencePromptLatent_{i}"
                }
            }
            reference_negprompt_latent_node = {
                "inputs": {
                    "conditioning": [last_negprompt_conditioning_node, 0],
                    "latent": [f"{200 + i*100 + 2}", 0]
                },
                "class_type": "ReferenceLatent",
                "_meta": {
                    "title": f"ReferenceNegPromptLatent_{i}"
                }
            }

            last_prompt_conditioning_node = f"{200 + i*100 + 3}"
            last_negprompt_conditioning_node = f"{200 + i*100 + 4}"

            workflow[f"{200 + i*100}"] = load_image_node
            workflow[f"{200 + i*100 + 1}"] = upscale_image_node
            workflow[f"{200 + i*100 + 2}"] = vae_encode_node
            workflow[f"{200 + i*100 + 3}"] = reference_prompt_latent_node
            workflow[f"{200 + i*100 + 4}"] = reference_negprompt_latent_node
        
        for node in workflow.values():
            if node.get("_meta", {}).get("title") == "KSampler":
                node["inputs"]["positive"] = [last_prompt_conditioning_node, 0]
                node["inputs"]["negative"] = [last_negprompt_conditioning_node, 0]
                break

        return workflow
    except Exception as e:
        logger.exception("Failed to insert prompt: %s", e)
        return workflow