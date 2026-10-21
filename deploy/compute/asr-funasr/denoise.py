"""Playback denoising (1.5, CUDA): MossFormer2_SE_48K, clearvoice's network with the pinned checkpoint. Only what
people listen to goes through it; transcription, diarization and voiceprints keep the original audio, since on real
meetings it made listening clearer and recognition no better (docs/ASR_EVAL.md, 录音降噪与去混响)."""

import argparse

import numpy as np

RATE = 16000
MODEL_RATE = 48000
# Seconds per block the model hears at once, and how much consecutive blocks share to fade from one into the next:
# a meeting of hours never sits in memory at 48 kHz.
BLOCK = 600
FADE = 2


class Denoiser:
    def __init__(self, checkpoint, device):
        import torch
        import torchaudio
        from clearvoice.models.mossformer2_se.mossformer2_se_wrapper import MossFormer2_SE_48K
        from clearvoice.utils.decode import decode_one_audio_mossformer2_se_48k

        # clearvoice's config/inference/MossFormer2_SE_48K.yaml
        self.args = argparse.Namespace(
            sampling_rate=MODEL_RATE, one_time_decode_length=20, decode_window=4, win_type="hamming", win_len=1920,
            win_inc=384, fft_len=1920, num_mels=60,
        )  # fmt: skip
        self.torch, self.torchaudio, self.device = torch, torchaudio, device
        self.decode = decode_one_audio_mossformer2_se_48k
        self.model = MossFormer2_SE_48K(self.args).model
        # The pinned checkpoint is the state dict itself, unlike MossFormer2_SS_16K's.
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        self.model.load_state_dict(state, strict=True)
        self.model.eval().to(device)

    def block(self, clip):
        resample = self.torchaudio.functional.resample
        up = resample(self.torch.from_numpy(clip), RATE, MODEL_RATE).numpy()
        with self.torch.inference_mode():
            out = self.decode(self.model, self.device, up[None], self.args)
        down = resample(self.torch.from_numpy(np.asarray(out, dtype=np.float32)), MODEL_RATE, RATE).numpy()
        return np.pad(down, (0, max(0, len(clip) - len(down))))[: len(clip)]

    def __call__(self, audio, progress=lambda fraction: None):
        """``audio``: 16 kHz mono float32; the denoised audio, as long, at the same rate."""
        step, fade = BLOCK * RATE, FADE * RATE
        result = np.zeros(len(audio), dtype=np.float32)
        for start in range(0, len(audio), step):
            begin = max(0, start - fade)
            piece = self.block(audio[begin : start + step])
            if begin < start:
                ramp = np.linspace(0.0, 1.0, start - begin, dtype=np.float32)
                result[begin:start] = result[begin:start] * (1 - ramp) + piece[: start - begin] * ramp
            result[start : begin + len(piece)] = piece[start - begin :]
            progress(min(1.0, (start + step) / len(audio)))
        return np.clip(result, -1.0, 1.0)
