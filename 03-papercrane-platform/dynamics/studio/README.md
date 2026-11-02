# SENBA Studio

View retained SENBA and source-model endpoints beside genuine recorded mdCATH frames. From this directory:

```sh
python3 start_saved_demo.py
```

Open http://127.0.0.1:8942. Python 3's standard library is sufficient. The molecular viewer, examples and Three.js dependencies are local. Use the Senba, Source model, MD endpoint and MD movie tabs, sample slider, atom view and Present button. Saved mode does not run the model.

Four saved transitions come from 1rquA01 at 450 K, replica 0. Each has sixteen independent endpoint draws per model and 51 recorded MD frames. A model animation is an illustrative input-to-endpoint interpolation. The MD movie uses chronological simulation coordinates. Playback seconds are display time.

For optional fresh local inference, install `requirements.txt` into your own Python environment. Place the released `senba.ckpt` at `../source-original/senba-sprint/artifacts/hf-release/senba.ckpt`, then run:

```sh
python3 start_demo.py
```

Open http://127.0.0.1:8941. The checkpoint must have SHA-256 `f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c`. `SENBA_ROOT` can select another complete SENBA sprint directory. CPU inference is supported; this portfolio's verification covers saved playback. Weights are available from [the pinned SENBA release](https://huggingface.co/vkali08/senba/tree/90cce9e822d511459a206ae3a06cbd8dbb243b09).

`prepare_data.py` rebuilds the saved model-coordinate JSON from the original derived JSONL arrays, which remain external. `prepare_trajectory.py` additionally requires the hash-pinned 1rquA01 HDF5 file in `runtime/`. Neither script is needed to view the saved examples.

The original app is `lambert-ga/senba-demo`. This copy retains the frame-export helper used for the maker video, original retained results and `SOURCE-MAP.json`. Fresh outputs write to `runtime/`. MarS-FM and Three.js use the MIT license; mdCATH is CC BY 4.0.

Saved-mode verification on 1 November 2026: the page and all seven bundled assets returned HTTP 200 with bytes matching this snapshot. Headless Chrome 156 rendered the viewer with WebGL 2.0; endpoint sample selection, source comparison and recorded-MD playback passed. Playback advanced the frame counter and changed the rendered canvas. The 390-pixel mobile view had no horizontal overflow, and no JavaScript page errors occurred. This check did not execute fresh model inference.
