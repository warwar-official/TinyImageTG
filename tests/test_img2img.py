import os
import sys
import asyncio
import unittest
import time

# Add parent directory to sys.path to allow importing local modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider import comfyui_send_prompt, comfyui_check_status, comfyui_load_image
from pipeline import load_workflows, insert_prompt, insert_image

class TestImg2Img(unittest.TestCase):

    def test_img2img(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        workflows = load_workflows()
        workflow = workflows.get("Text-to-Img", {})
        prompt = "keep style, make it look a village"
        workflow = insert_prompt(workflow, prompt)
        image_path = [os.path.join(base_dir, "tests", "images", "test_img2img.png")]
        workflow = insert_image(workflow, image_path)
        result = asyncio.run(comfyui_send_prompt(workflow))
        self.assertFalse(result.get('error'))
        prompt_id = result.get('prompt_id')
        completed = False
        for _ in range(300):
            status = asyncio.run(comfyui_check_status(prompt_id))
            if status.get('completed'):
                completed = True
                images = status.get("images", [])
                print("Generation completed successfully!")
                break
            time.sleep(2)
        self.assertTrue(completed, "ComfyUI generation timed out or failed to complete")
        self.assertTrue(len(images) > 0, "No output images returned from ComfyUI")
        
        img_info = images[0]
        filename = img_info["filename"]
        subfolder = img_info["subfolder"]
        img_type = img_info["type"]
        
        img_bytes = asyncio.run(comfyui_load_image(filename, subfolder, img_type))
        self.assertTrue(isinstance(img_bytes, bytes), f"Failed to load image. Result: {img_bytes}")
        
        
        output_file_path = os.path.join(base_dir, "tests", "images", "test_img2img_output.png")
        with open(output_file_path, "wb") as img_file:
            img_file.write(img_bytes)
        self.assertTrue(os.path.exists(output_file_path), f"Failed to save image file to {output_file_path}")
        self.assertTrue(os.path.getsize(output_file_path) > 0, "Saved image file is empty")
        
        print(f"Success! Generated image saved to: {output_file_path}")

if __name__ == "__main__":
    unittest.main()