# Trial courseware publication and timeline MP4

Both trial modes can be published through the existing teacher-confirmed course/lesson
placement flow. Completion, audio, current video version and published-version checks
still apply. Drafts remain private until the teacher publishes; editing does not
overwrite the pinned student video. Interactive and quiz scenes remain web activities.

Only `coursewareTrial.mode = learning-skills-enhanced` without a native PPTX uses
`openmaic-timeline-v1`. Regular courseware and faithful/native PPTX keep the existing
recorder. The renderer identity participates in the clip and plan cache keys.

The immutable page snapshot is compiled by OpenMAIC's `compileVideoTimeline`, using
measured narration durations and rendered element geometry. `emitHyperframes` emits
a paused GSAP composition; slide PNGs, transparent reveal layers, audio and the
vendored GSAP runtime are packaged locally. The existing video worker renders this
project using `@hyperframes/producer` instead of waiting through classroom playback.
It validates H.264/AAC and duration before atomically publishing the clip and timing.
Subtitles use that timing through the existing student/teacher player.

This trial supports speech, spotlight, laser and generic reveal (fade, fade-up,
scale). Native PPTX steps and unsupported live actions fail explicitly instead of
silently disappearing. Their support must be validated before expanding the trial.
Each producer requests one render worker; existing first-page priority, two page
lanes, cache reuse and per-page retry remain in effect. This architecture alone
does not guarantee a speedup; benchmark real lessons including compile and encode.

The app requires the worker `/health` response to advertise `openmaic-timeline-v1`.
Deploy the compatible worker before switching the teacher image. The worker image
includes its locked producer dependency, Chromium and FFmpeg; no separate service
or public render endpoint is required. The media revision script includes the new
timeline contract, so teacher auto-deployment detects corresponding worker changes.

Validation includes teacher publication boundaries, cache isolation, exact speech
offsets, hidden-before-reveal snapshots, deterministic reveal reset after seeking,
project extraction bounds, and actual MP4 audio/video/frame inspection.
