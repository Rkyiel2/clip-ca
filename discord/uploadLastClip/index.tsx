/*
 * UploadLastClip - upload the newest Clip Ça clip, trimmed and compressed for Discord.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { NavContextMenuPatchCallback } from "@api/ContextMenu";
import { definePluginSettings } from "@api/Settings";
import { UploadIcon } from "@components/Icons";
import definePlugin, { OptionType, PluginNative } from "@utils/types";
import { Channel, RenderModalProps } from "@vencord/discord-types";
import { DraftType, Menu, Modal, openModal, UploadHandler, useEffect, useRef, useState } from "@webpack/common";

const Native = VencordNative.pluginHelpers.UploadLastClip as PluginNative<typeof import("./native")>;

const settings = definePluginSettings({
    maxSizeMB: {
        type: OptionType.NUMBER,
        description: "Max file size in MB (10 without Nitro, 50 Nitro Basic, 500 Nitro)",
        default: 10
    }
});

const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

function ClipModal({ modalProps, channel }: { modalProps: RenderModalProps; channel: Channel; }) {
    const [clip, setClip] = useState<{ name: string; path: string; size: number; }>();
    const [url, setUrl] = useState<string>();
    const [error, setError] = useState<string>();
    const [duration, setDuration] = useState(0);
    const [start, setStart] = useState(0);
    const [end, setEnd] = useState(0);
    const [busy, setBusy] = useState(false);
    const video = useRef<HTMLVideoElement>(null);

    useEffect(() => {
        let objectUrl: string | undefined;
        (async () => {
            const last = await Native.getLastClip();
            if (!last) return setError("No clips found in your Clip Ça folder.");
            setClip(last);
            objectUrl = URL.createObjectURL(new Blob([await Native.readClip(last.path)], { type: "video/mp4" }));
            setUrl(objectUrl);
        })().catch(e => setError(String(e?.message ?? e)));
        return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
    }, []);

    const seek = (t: number) => { if (video.current) video.current.currentTime = t; };

    async function upload() {
        setBusy(true);
        try {
            const bytes = await Native.compressClip(clip!.path, start, end, duration, settings.store.maxSizeMB * 1_000_000);
            const file = new File([bytes], clip!.name.replace(/\.\w+$/, ".mp4"), { type: "video/mp4" });
            UploadHandler.promptToUpload([file], channel, DraftType.ChannelMessage);
            modalProps.onClose();
        } catch (e: any) {
            setError(String(e?.message ?? e));
            setBusy(false);
        }
    }

    return (
        <Modal
            {...modalProps}
            title="Upload Last Clip"
            actions={[{
                text: busy ? "Compressing..." : "Upload",
                variant: "primary",
                onClick: upload,
                disabled: busy || !duration
            }]}
        >
            {error && <div style={{ color: "var(--text-feedback-critical)", marginBottom: 8 }}>{error}</div>}
            {!url && !error && <div style={{ color: "var(--text-default)" }}>Loading clip...</div>}
            {url && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, color: "var(--text-default)" }}>
                    <video
                        ref={video}
                        src={url}
                        controls
                        style={{ width: "100%", maxHeight: 360, borderRadius: 8, background: "black" }}
                        onLoadedMetadata={e => { const d = e.currentTarget.duration; setDuration(d); setEnd(d); }}
                        onTimeUpdate={e => { if (e.currentTarget.currentTime > end) e.currentTarget.pause(); }}
                    />
                    <label>
                        Start: {fmt(start)}
                        <input type="range" min={0} max={duration} step={0.1} value={start} style={{ width: "100%" }} aria-label="Trim start"
                            onChange={e => { const v = Math.min(+e.currentTarget.value, end - 0.5); setStart(v); seek(v); }} />
                    </label>
                    <label>
                        End: {fmt(end)}
                        <input type="range" min={0} max={duration} step={0.1} value={end} style={{ width: "100%" }} aria-label="Trim end"
                            onChange={e => { const v = Math.max(+e.currentTarget.value, start + 0.5); setEnd(v); seek(v); }} />
                    </label>
                    <div style={{ fontSize: 12, opacity: 0.7 }}>
                        {clip?.name} · {(clip!.size / 1e6).toFixed(1)} MB · sending {fmt(end - start)}, compressed under {settings.store.maxSizeMB} MB
                    </div>
                </div>
            )}
        </Modal>
    );
}

const ctxMenuPatch: NavContextMenuPatchCallback = (children, { channel }) => {
    children.push(
        <Menu.MenuItem
            id="vc-upload-last-clip"
            label="Upload Last Clip"
            iconLeft={UploadIcon}
            leadingAccessory={{ type: "icon", icon: UploadIcon }}
            action={() => openModal(props => <ClipModal modalProps={props} channel={channel} />)}
        />
    );
};

export default definePlugin({
    name: "UploadLastClip",
    description: "Adds \"Upload Last Clip\" to the + menu: sends your newest Clip Ça clip, optionally trimmed, compressed to fit Discord's size limit.",
    authors: [{ name: "Rkyiel2", id: 0n }],
    settings,
    contextMenus: {
        "channel-attach": ctxMenuPatch
    }
});
