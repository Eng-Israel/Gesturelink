# Gesturelink

Gesturelink is a browser-based conference prototype with real peer-to-peer audio/video calls and a separate sign-language research demo.

## Run a conference

Install the API dependencies once:

```powershell
python -m pip install -r backend\requirements.txt
```

Start the conference and inference server from the project folder:

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` on the computer, enter a display name, and join. Copy the invite link to let up to five other people join the same room. The room is created from the link and is not stored. Leave the call to stop sending your camera and microphone.

### Test a call between your computer and phone

Phone browsers require HTTPS for camera and microphone access. A LAN address such as `http://192.168.1.10:8000` is not secure, even when both devices are on the same Wi-Fi. For a quick test, expose the local server through a temporary Cloudflare HTTPS tunnel:

1. Start the app on your computer with the Uvicorn command above and leave that terminal open.
2. If needed, install `cloudflared` from PowerShell with `winget install --id Cloudflare.cloudflared`. Open a second PowerShell window and run:

   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```

3. Copy the `https://....trycloudflare.com` URL printed by the tunnel. Open it on the computer, enter a name, and select **Join conference**. Allow camera and microphone access.
4. Select **Copy invite** in the computer's browser and open that full invite URL on your phone. Use the same browser URL, allow camera and microphone access, enter a different name, and select **Join conference**.
5. Keep both devices on the same Wi-Fi for the first test. You should see the other participant's video on each device. Use headphones or mute one microphone to prevent audio feedback.

The tunnel URL is temporary; keep the tunnel terminal running during the call. Stop it with Ctrl+C when finished, and also stop the Uvicorn server. The tunnel makes the app publicly reachable while active, so only share the invite with people you trust and do not use it for private calls. The demo uses Google's public STUN service for peer discovery and does not include a TURN relay, so restrictive networks may prevent calls. Call media is not recorded or relayed through this app's server.

This is a website, not a native Android/iOS package. It can be added to a phone's home screen when hosted securely, but a signed APK or App Store app has not been produced.

### Build a portable Windows folder

The portable build bundles the server runtime, trained model, hand-landmarker asset, and all available sign videos. A recipient does not need to install Python or download project dependencies; they need a Windows browser. The full video collection makes the folder large.

Build it from the project directory in PowerShell:

```powershell
python -m pip install -r backend\requirements.txt
python -m pip install -r packaging\requirements-build.txt
.\packaging\build-portable.ps1
```

The result is `dist\Gesturelink\`. Copy or zip the entire folder, then the recipient extracts it and opens `Gesturelink.exe`. The app starts its local server and opens the browser. Keep the console window open while using it; press Enter there to shut down. This local portable build is for use on that computer; remote conference access still requires an HTTPS host or tunnel as described above.

For the ready-to-run Windows bundle, download `Gesturelink-windows-x64.zip` from the repository's **Releases** page, extract the complete folder, and run `Gesturelink.exe`. The bundle includes the sign-video library; share it only with people authorized to access the dataset under its terms.

## Use recorded public videos

For a quick ASL baseline, WLASL is a public academic dataset with labeled recorded videos. It is not KSL, so use it to test the pipeline only, not as a claim of KSL accuracy. Download a small subset:

```powershell
python dataset\download_wlasl.py --metadata-only
python -m pip install yt-dlp
python dataset\download_wlasl.py --labels hello,thank_you,yes,no --per-label 5
```

The selected metadata is saved in `dataset/manifest.json` and clips in `dataset/videos/`. Review WLASL's C-UDA terms before using the files; the dataset is restricted to academic/computational use.

Convert downloaded clips into training landmarks:

```powershell
python dataset\prepare_wlasl.py
```

This writes WLASL landmark samples into `backend/data/`, where they can be combined with locally recorded samples.

To create a compact sign-reference library from a WLASL video-ID backup, with one playable clip per sign and no duplicate-word output clips, run with FFmpeg installed:

```powershell
python dataset\restore_wlasl_videos.py --raw-videos "C:\Users\Admin\OneDrive\Desktop\sign training video\raw_videos"
```

The restore tool picks one playable clip for every sign with a valid local source, converts it to a compact browser-compatible MP4, and updates the manifest. The speech-to-sign panel indexes the available local clips automatically.

### Train the 20-sign ASL camera model

The core recognizer uses these 20 signs: hello, you, want, need, go, eat, drink, water, help, please, thank you, yes, no, what, where, who, good, home, today, and more.

Train from the labelled raw WLASL video-ID backup:

```powershell
python dataset\train_core_vocabulary.py --raw-videos "C:\Users\Admin\OneDrive\Desktop\sign training video\raw_videos"
```

The script extracts up to 12 evenly spaced frames per clip, keeps WLASL's train/validation/test clip splits separate for evaluation, trains an MLP for 150 epochs, and saves its held-out evaluation report to `backend/gesture_model_metadata.json`. It then fits the final model with all matching clips and saves the 20-sign classifier to `backend/gesture_model.joblib`. Restart the API after training so it loads the new model.

To collect additional local KSL signs, open `/collector.html` over HTTPS or localhost. Enter one sign label and capture 20-50 samples, ideally from multiple signers. The API stores frames and MediaPipe landmarks in `backend/data/<label>/`. The generic `backend\train_model.py` script trains on those collection folders and replaces the core ASL model, so run the dedicated 20-sign script again to restore the WLASL core model.

The live room sends camera frames to `/infer-posture` when Sign to speech is selected. Predictions above 50% confidence appear in the live transcript immediately and, after **Enable speech** is tapped once, are spoken individually. A five-second pause finishes the current phrase; **Speak sentence** reads the complete phrase aloud. Sentence wording uses simple English rules (for example, adding “I” before an action); this is a prototype gloss-to-speech aid, not full sign-language translation. The model classifies individual frames into its 20 trained signs; it does not recognize arbitrary signs or interpret continuous sign motion.

## Current scope and limitations

- The call uses a mesh of WebRTC connections (one to six participants) with live camera, microphone mute, and screen sharing.
- The room server only coordinates peers; it does not store room membership or relay call media.
- Translation is still a prototype: speech recognition and spoken output depend on browser support, sign clips and the 20-sign camera model use ASL/WLASL rather than KSL, and sentence wording is based on simple rules. The frame classifier is not a complete, validated sign-language recognition system and cannot translate continuous motion.
