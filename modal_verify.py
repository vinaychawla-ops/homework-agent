"""One-off verification that the OpenRouter secret reaches the container and
the VLM handwriting path works from Modal's network.

Run with: modal run modal_verify.py
"""

import modal

from modal_app import app, image


@app.function(
    image=image,
    timeout=600,
    secrets=[modal.Secret.from_name("openrouter-api-key")],
)
def check_vlm():
    import os
    import sys

    sys.path.insert(0, "/root")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not injected into container")

    from homework_agent import ocr

    text = ocr.transcribe_handwriting("/root/data/samples/science_homework.png")
    return {"key_prefix": key[:3] + "...", "chars": len(text), "head": text[:200]}


@app.local_entrypoint()
def main():
    result = check_vlm.remote()
    print("VLM OK:", result)
