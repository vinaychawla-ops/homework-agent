"""Homework Grader on Modal (free $30/mo credits).

Deploy with:
    modal deploy modal_app.py

This builds a container image with Docling + Gradio, bakes the OCR models
into the image at build time, and serves the Gradio UI as an ASGI app at a
public https://...modal.run URL.

Handwriting VLM mode needs an `OPENROUTER_API_KEY`: add it as a Modal secret
named `openrouter-api-key` in the dashboard (Secrets -> New secret), no
redeploy required. Without it, image grading uses the local Docling pipeline.
"""

import modal

app = modal.App("homework-grader")

# Shared volume for Gradio uploads. Modal can route the upload POST and the
# grading request to different containers; without a shared temp dir the
# grading container cannot see the uploaded file (FileNotFoundError).
uploads_volume = modal.Volume.from_name(
    "homework-grader-uploads", create_if_missing=True
)


def warmup_docling() -> None:
    """Download Docling's local OCR models at image build time."""
    import sys

    sys.path.insert(0, "/root")
    from homework_agent import ocr

    text = ocr.extract_printed("/root/data/samples/science_homework.png")
    print(f"warmup OCR chars: {len(text)}")


image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libsm6", "libxext6")
    .pip_install_from_requirements("requirements.txt")
    .pip_install("gradio>=5.0", "fastapi")
    .add_local_dir("homework_agent", remote_path="/root/homework_agent", copy=True)
    .add_local_dir("data", remote_path="/root/data", copy=True)
    .add_local_file("space/app.py", remote_path="/root/app.py", copy=True)
    .run_function(warmup_docling, timeout=1800)
)


@app.function(
    image=image,
    cpu=2,
    memory=8192,
    timeout=900,
    secrets=[modal.Secret.from_name("openrouter-api-key")],
    volumes={"/gradio-tmp": uploads_volume},
    env={"GRADIO_TEMP_DIR": "/gradio-tmp"},
)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, "/root")
    from fastapi import FastAPI

    import gradio as gr

    from app import demo

    fastapi_app = FastAPI()
    return gr.mount_gradio_app(fastapi_app, demo, path="/")
