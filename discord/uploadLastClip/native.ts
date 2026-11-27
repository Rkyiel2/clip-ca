/*
 * UploadLastClip - upload the newest Clip Ça clip, trimmed and compressed for Discord.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { execFile } from "child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { readFile, rm } from "fs/promises";
import { homedir, tmpdir } from "os";
import { extname, join, normalize, sep } from "path";

const VIDEO_EXT = new Set([".mp4", ".mkv", ".mov", ".webm"]);

function clipFolder() {
    try {
        const config = process.platform === "win32" ? process.env.APPDATA! : process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
        const s = JSON.parse(readFileSync(join(config, "ClipCa", "settings.json"), "utf8"));
        if (s.folder) return normalize(s.folder);
    } catch { }
    return join(homedir(), "Videos", "Clips");
}

// Discord is often started before ffmpeg landed on PATH, so also look where winget puts it.
function ffmpegPath() {
    const pkgs = join(process.env.LOCALAPPDATA!, "Microsoft", "WinGet", "Packages");
    try {
        for (const pkg of readdirSync(pkgs).filter(d => d.startsWith("Gyan.FFmpeg"))) {
            for (const build of readdirSync(join(pkgs, pkg))) {
                const exe = join(pkgs, pkg, build, "bin", "ffmpeg.exe");
                if (existsSync(exe)) return exe;
            }
        }
    } catch { }
    return "ffmpeg";
}

function run(args: string[]) {
    return new Promise<void>((resolve, reject) =>
        execFile(ffmpegPath(), args, { windowsHide: true, maxBuffer: 64 * 1024 * 1024 }, (err, _out, stderr) =>
            err ? reject(new Error(stderr.split("\n").filter(Boolean).slice(-3).join("\n") || err.message)) : resolve()
        )
    );
}

export function getLastClip() {
    const dir = clipFolder();
    const clips = readdirSync(dir)
        .filter(f => VIDEO_EXT.has(extname(f).toLowerCase()))
        .map(f => ({ name: f, path: join(dir, f), ...statSync(join(dir, f)) }))
        .sort((a, b) => b.mtimeMs - a.mtimeMs);
    if (!clips.length) return null;
    const { name, path, size } = clips[0];
    return { name, path, size };
}

function checkPath(path: string) {
    path = normalize(path);
    if (!path.startsWith(clipFolder() + sep) || !VIDEO_EXT.has(extname(path).toLowerCase()))
        throw new Error("Not a clip: " + path);
    return path;
}

export async function readClip(_, path: string) {
    return new Uint8Array(await readFile(checkPath(path)));
}

/**
 * Trims to [start, end] seconds and fits it under maxBytes. Returns the mp4 bytes.
 * Lossless when it can be (original file, or a stream-copied cut); re-encodes only when that is still too big.
 */
export async function compressClip(_, path: string, start: number, end: number, duration: number, maxBytes: number) {
    path = checkPath(path);
    const trimmed = start > 0.05 || end < duration - 0.05;
    if (!trimmed && statSync(path).size <= maxBytes) return new Uint8Array(await readFile(path));

    const len = end - start;
    const out = join(tmpdir(), `vc-clip-${Date.now()}.mp4`);
    // 0.9: headroom for mp4 container overhead and encoder overshoot
    let totalKbps = maxBytes * 8 * 0.9 / len / 1000;
    let useNvenc = true;

    try {
        if (trimmed) {
            // lossless cut: streams copied untouched, so the start snaps back to the nearest keyframe
            await run(["-y", "-ss", String(start), "-to", String(end), "-i", path, "-c", "copy",
                "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out]);
            if (statSync(out).size <= maxBytes) return new Uint8Array(await readFile(out));
        }

        for (let attempt = 0; attempt < 4; attempt++) {
            const audioKbps = totalKbps > 1000 ? 128 : totalKbps > 300 ? 96 : 48;
            const videoKbps = Math.max(50, Math.floor(totalKbps - audioKbps));
            const height = videoKbps > 5000 ? 1080 : videoKbps > 2000 ? 720 : videoKbps > 800 ? 480 : 360;
            const fps = videoKbps > 2500 ? 60 : 30;
            const encoder = useNvenc
                ? ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-multipass", "fullres"]
                : ["-c:v", "libx264", "-preset", "veryfast"];

            const args = [
                "-y", "-ss", String(start), "-to", String(end), "-i", path,
                "-vf", `scale=-2:'min(${height},ih)',fps='min(${fps},source_fps)'`,
                ...encoder,
                "-b:v", `${videoKbps}k`, "-maxrate", `${Math.floor(videoKbps * 1.3)}k`, "-bufsize", `${videoKbps * 2}k`,
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", `${audioKbps}k`, "-ac", "2",
                "-movflags", "+faststart", out
            ];
            try {
                await run(args);
            } catch (e) {
                if (!useNvenc) throw e;
                useNvenc = false; // no NVIDIA GPU / driver: fall back to CPU
                attempt--;
                continue;
            }
            const size = statSync(out).size;
            if (size <= maxBytes) return new Uint8Array(await readFile(out));
            totalKbps *= maxBytes / size * 0.9;
        }
        throw new Error("Could not get the clip under the size limit. Trim it shorter.");
    } finally {
        rm(out, { force: true }).catch(() => { });
    }
}
