# Tiny Image TG Bot

Telegram bot for image generation using ComfyUI and llamap.cpp.

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Your `.env` file should look like this:

```env
TELEGRAM_TOKEN = your_bot_token_here
```

All inference infrastructure URL hardcoded as a default local ComfyUI and llama.cpp.
All paths relative to the project root.

## Workflows

Example workflow for image generation based on the FLUX.2 pipeline and optimized for this model.

Image-to-Image this style could not work with another models, need edit or replace workflow json file for it.

For using Text-to-Image your workflow should contain next nodes (essential for any cases):

class: PrimitiveStringMultiline

title: Prompt

class: PrimitiveStringMultiline

title: NegPrompt

class: PrimitiveInt

title: Seed

For using Image-to-Image your workflow should contain next nodes (only for img2img part):

class: VAEDecode

title: VAE Decode

class: KSampler

title: KSampler

Example workflow using custome node: `TiledDiffusion` that can be removed from workflow in case if you don't have it on ComfyUI.

Example workflow using custome node: `GGUFLoader` that can be replaces with loader for safetensors models in case if you don't have it on ComfyUI.

**IMPORTANT:** Example workflow uses uncensored version of CLIP so it is have no build in guardrails against generating not safe for work content. Use it on your own risk.

## Prompt optimization

Bot automaticaly use LLM for prompt optimization using llama.cpp. For it need to start llama.cpp with right prompt and model or just edit `prompts.yaml` file. By default bot will try to use `system_prompt` from `prompts.yaml` for optimization.

In case if `[NO ENCHANCE]` tag will be found in prompt, bot will skip prompt optimization.

If llama.cpp will be not available or will return error, bot will send original prompt to ComfyUI.

**IMPORTANT:** If you want to use uncensored version of workflow, you should use uncensored model for prompt optimization too.

## Comfy UI

For image generation you should have:

FLUX.2 Klein 9B - generation model (unsloth version recommended, if you use GGUF)

FLUX.2 VAE - vae model (any version will work, but do not quantize it)

Qwen3-8B - encoder model (unsloth version recommended, if you use GGUF)
