"""Inference-only FireRed AED beam-1 decoding with incremental self-attention keys/values.

The worker consumes only yseq. Other beam/search modes retain the upstream implementation, including its
confidence values. Attention uses PyTorch SDPA with the same keep-mask and scale as FireRed's implementation.
"""


def inference_dtype(torch, device):
    """Use native CUDA BF16 only; CPU, MPS and older GPUs keep the FP32 weights/features."""
    device = torch.device(device)
    if device.type == "cuda":
        with torch.cuda.device(device):
            if torch.cuda.get_device_capability(device)[0] >= 8 and torch.cuda.is_bf16_supported():
                return torch.bfloat16
    return torch.float32


def install_greedy_decoder(decoder):
    import torch

    original = decoder.batch_beam_search

    def attention(q, k, v, mask=None):
        return torch.nn.functional.scaled_dot_product_attention(
            q, k, v, attn_mask=mask.bool() if mask is not None else None, dropout_p=0.0
        )

    for layer in decoder.layer_stack:
        layer.self_attn.attention.forward = attention
        layer.cross_attn.attention.forward = attention

    def decode(
        encoder_outputs,
        src_masks,
        beam_size=1,
        nbest=1,
        decode_max_len=0,
        softmax_smoothing=1.0,
        length_penalty=0.0,
        eos_penalty=1.0,
        elm=None,
        elm_weight=0.0,
    ):
        if decoder.training or beam_size != 1 or nbest != 1 or elm is not None or eos_penalty != 1.0:
            return original(
                encoder_outputs,
                src_masks,
                beam_size,
                nbest,
                decode_max_len,
                softmax_smoothing,
                length_penalty,
                eos_penalty,
                elm,
                elm_weight,
            )
        return greedy_decode(decoder, encoder_outputs, src_masks, decode_max_len, softmax_smoothing)

    decoder.batch_beam_search = decode


def greedy_decode(decoder, encoder_outputs, src_masks, decode_max_len, softmax_smoothing):
    import torch

    batch, frames, _ = encoder_outputs.shape
    ys = torch.full((batch, 1), decoder.sos_id, dtype=torch.long, device=encoder_outputs.device)
    finished = torch.zeros(batch, dtype=torch.bool, device=ys.device)
    # Request-local caches: a shorter next batch must never inherit tokens or projections from this one.
    caches = [None] * decoder.n_layers
    for step in range(decode_max_len if decode_max_len > 0 else frames):
        mask = (ys != decoder.pad_id).unsqueeze(1)
        x = decoder.tgt_word_emb(ys[:, -1:]) * decoder.scale + decoder.positional_encoding.pe[:, step : step + 1]
        for i, layer in enumerate(decoder.layer_stack):
            residual = x
            norm = layer.self_attn_norm(x)
            attention = layer.self_attn
            q = attention.w_qs(norm).view(batch, 1, attention.n_head, attention.d_k).transpose(1, 2)
            k = attention.w_ks(norm).view(batch, 1, attention.n_head, attention.d_k).transpose(1, 2)
            v = attention.w_vs(norm).view(batch, 1, attention.n_head, attention.d_k).transpose(1, 2)
            if caches[i] is not None:
                k = torch.cat((caches[i][0], k), dim=2)
                v = torch.cat((caches[i][1], v), dim=2)
            caches[i] = (k, v)
            h = attention.attention(q, k, v, mask=mask.unsqueeze(1))
            x = residual + attention.fc(h.transpose(1, 2).contiguous().view(batch, 1, attention.d_model))
            x = x + layer.cross_attn(layer.cross_attn_norm(x), encoder_outputs, encoder_outputs, mask=src_masks)
            x = x + layer.mlp(layer.mlp_norm(x))
        logits = decoder.tgt_word_prj(decoder.layer_norm_out(x)[:, -1])
        # Keep upstream topk tie-breaking and smoothing. Beam 1 cannot change the winner by length penalty.
        scores = torch.nn.functional.log_softmax(logits / softmax_smoothing, dim=-1)
        token = torch.topk(scores, k=1, dim=1).indices.squeeze(1)
        token = torch.where(finished, decoder.eos_id, token)
        ys = torch.cat((ys, token[:, None]), dim=1)
        finished = token == decoder.eos_id
        if finished.all().item():
            break
    lengths = (ys != decoder.eos_id).sum(dim=1).tolist()
    return [[{"yseq": ys[i, 1:length]}] for i, length in enumerate(lengths)]
