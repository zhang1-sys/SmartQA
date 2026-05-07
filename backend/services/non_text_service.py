from __future__ import annotations

import base64
import time
from typing import Any

import requests

from config import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, AZURE_VISION_ENDPOINT, AZURE_VISION_KEY


class NonTextProcessingError(RuntimeError):
    pass


class NonTextService:
    def transcribe_image(self, data: bytes, content_type: str) -> dict[str, Any]:
        if not (AZURE_VISION_ENDPOINT and AZURE_VISION_KEY):
            raise NonTextProcessingError("azure_vision_not_configured")
        endpoint = AZURE_VISION_ENDPOINT.rstrip("/")
        response = requests.post(
            f"{endpoint}/computervision/imageanalysis:analyze",
            params={"features": "read", "api-version": "2024-02-01"},
            headers={"Ocp-Apim-Subscription-Key": AZURE_VISION_KEY, "Content-Type": content_type or "application/octet-stream"},
            data=data,
            timeout=60,
        )
        if not response.ok:
            raise NonTextProcessingError(f"azure_vision_failed:{response.status_code}:{response.text[:500]}")
        body = response.json()
        lines = []
        read_result = (body.get("readResult") or {})
        for block in read_result.get("blocks") or []:
            for line in block.get("lines") or []:
                text = (line.get("text") or "").strip()
                if text:
                    lines.append(text)
        return {"kind": "image", "text": "\n".join(lines), "raw": body}

    def transcribe_audio(self, data: bytes, content_type: str) -> dict[str, Any]:
        if not (AZURE_SPEECH_REGION and AZURE_SPEECH_KEY):
            raise NonTextProcessingError("azure_speech_not_configured")
        if "wav" not in (content_type or "").lower():
            raise NonTextProcessingError("azure_speech_requires_wav_audio")
        token = self._speech_token()
        response = requests.post(
            f"https://{AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
            params={"language": "zh-CN", "format": "detailed"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            data=data,
            timeout=60,
        )
        if not response.ok:
            raise NonTextProcessingError(f"azure_speech_failed:{response.status_code}:{response.text[:500]}")
        body = response.json()
        text = body.get("DisplayText") or ""
        if not text and body.get("NBest"):
            text = body["NBest"][0].get("Display") or body["NBest"][0].get("Lexical") or ""
        return {"kind": "audio", "text": text.strip(), "raw": body}

    def _speech_token(self) -> str:
        response = requests.post(
            f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
            headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY},
            timeout=20,
        )
        if not response.ok:
            raise NonTextProcessingError(f"azure_speech_token_failed:{response.status_code}:{response.text[:300]}")
        return response.text


def file_to_data_url(data: bytes, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
