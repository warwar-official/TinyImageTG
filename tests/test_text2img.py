import os
import sys
import json
import asyncio
import unittest
import time

# Add parent directory to sys.path to allow importing local modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider import comfyui_send_prompt, comfyui_check_status, comfyui_load_image
from pipeline import load_workflows, insert_prompt

class TestComfyUIText2Img(unittest.TestCase):
    
    def test_text2img_generation(self):
        # 1. Resolve paths relative to this file
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        workflows = load_workflows()
        workflow = workflows.get("Text-to-Img", {})
        prompt = "A beautiful high-detail cinematic photograph of a futuristic neon city street, cyberpunk style"
        workflow = insert_prompt(workflow, prompt)
            
        print("\nSending prompt to ComfyUI...")
        result = asyncio.run(comfyui_send_prompt(workflow))
        
        # Check send result
        self.assertIsNotNone(result, "Send result is None")
        self.assertNotIn("error", result, f"Error sending prompt: {result.get('error')}")
        prompt_id = result.get("prompt_id")
        self.assertIsNotNone(prompt_id, "prompt_id is missing in send result")
        print(f"Prompt queued successfully. Prompt ID: {prompt_id}")
        
        # 4. Poll for status
        completed = False
        images = []
        max_retries = 300  # 30 retries * 2 seconds = 60 seconds max
        for attempt in range(max_retries):
            print(f"Checking status (attempt {attempt + 1}/{max_retries})...")
            status = asyncio.run(comfyui_check_status(prompt_id))
            
            if status.get("completed"):
                completed = True
                images = status.get("images", [])
                print("Generation completed successfully!")
                break
                
            if status.get("error"):
                print(f"Status check error: {status['error']}")
                
            time.sleep(2)
            
        self.assertTrue(completed, "ComfyUI generation timed out or failed to complete")
        self.assertTrue(len(images) > 0, "No output images returned from ComfyUI")
        
        # 5. Load and Save Image
        img_info = images[0]
        filename = img_info["filename"]
        subfolder = img_info["subfolder"]
        img_type = img_info["type"]
        
        print(f"Loading image: {filename} (subfolder: '{subfolder}', type: '{img_type}')...")
        img_bytes = asyncio.run(comfyui_load_image(filename, subfolder, img_type))
        
        self.assertTrue(isinstance(img_bytes, bytes), f"Failed to load image. Result: {img_bytes}")
        
        # Write to file
        output_file_path = os.path.join(base_dir, "tests", "images", "test_text2img_output.png")
        with open(output_file_path, "wb") as img_file:
            img_file.write(img_bytes)
            
        self.assertTrue(os.path.exists(output_file_path), f"Failed to save image file to {output_file_path}")
        self.assertTrue(os.path.getsize(output_file_path) > 0, "Saved image file is empty")
        
        print(f"Success! Generated image saved to: {output_file_path}")

if __name__ == "__main__":
    unittest.main()
