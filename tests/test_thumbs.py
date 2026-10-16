"""Library card thumbnails: small WebP copies of large previews, made once."""
import os
import time

import test_shared as T

check = T.check


def main():
    base, user = T.fake_install("THUMBS")
    smf = T.load_smf(base, user)
    from PIL import Image
    os.makedirs(T.LORA, exist_ok=True)
    big = os.path.join(T.LORA, "big.preview.png")
    Image.effect_noise((1600, 2400), 90).convert("RGB").save(big)  # noise doesn't compress: a multi-MB PNG
    small = os.path.join(T.LORA, "small.preview.jpeg")
    Image.new("RGB", (64, 64), "red").save(small)
    vid = os.path.join(T.LORA, "clip.preview.mp4")
    open(vid, "wb").write(b"x" * 300_000)

    t = smf.thumbs.thumb_for(big, 448)
    check(t != big and t.endswith(".webp") and os.path.getsize(t) < os.path.getsize(big) / 5, f"a large PNG gets a small WebP ({os.path.getsize(big)} → {os.path.getsize(t)} bytes)")
    with Image.open(t) as im:
        check(im.size[0] == 448, f"448 px wide ({im.size})")
    m = os.path.getmtime(t)
    time.sleep(0.05)
    check(smf.thumbs.thumb_for(big, 448) == t and os.path.getmtime(t) == m, "made once, then reused")
    os.utime(big, (time.time() + 5,) * 2)
    check(smf.thumbs.thumb_for(big, 448) != t, "a changed preview gets a new thumbnail")
    check(smf.thumbs.thumb_for(small, 448) == small and smf.thumbs.thumb_for(vid, 448) == vid, "small images and videos are served as they are")
    bad = os.path.join(T.LORA, "broken.preview.png")
    open(bad, "wb").write(b"not an image" * 20000)
    check(smf.thumbs.thumb_for(bad, 448) == bad, "an unreadable image falls back to the original")
    check(smf.thumbs.thumb_for(os.path.join(T.LORA, "gone.png")).endswith("gone.png"), "a missing file doesn't raise")
    for p in (big, small, vid, bad):
        os.remove(p)
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
