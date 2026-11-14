const $ = id => document.getElementById(id);
let mediaUrl = "";
let playlistEntries = [];

function formatBytes(bytes) {
    if (!bytes || isNaN(bytes)) return "";
    const mb = bytes / (1024 * 1024);
    return mb >= 1 ? ` · ${mb.toFixed(1)} MB` : ` · ${(bytes / 1024).toFixed(0)} KB`;
}

function formatDuration(sec) {
    if (!sec || isNaN(sec)) return "";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return ` · ${m}:${s < 10 ? "0" : ""}${s}`;
}

$("inspect").addEventListener("click", async () => {
    mediaUrl = $("url").value.trim();

    if (!mediaUrl) {
        $("status").textContent = "Please enter a valid URL.";
        return;
    }

    $("inspect").disabled = true;
    $("status").textContent = "Analyzing media... Please wait.";
    $("result").classList.add("hidden");

    try {
        const response = await fetch("/api/info", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url: mediaUrl})
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Analysis failed");

        $("title").textContent = data.title || "Untitled media";
        if (data.thumbnail) {
            $("thumbnail").src = data.thumbnail;
            $("thumbnail").style.display = "block";
        } else {
            $("thumbnail").style.display = "none";
        }
        $("details").textContent =
            "Uploader: " + (data.uploader || "Unknown") + formatDuration(data.duration);

        const isPlaylist = data.type === "playlist";

        $("singleControls").classList.toggle("hidden", isPlaylist);
        $("playlistControls").classList.toggle("hidden", !isPlaylist);

        if (isPlaylist) {
            playlistEntries = data.entries || [];
            $("details").textContent += " · " + playlistEntries.length + " videos";
            renderPlaylist();
        } else {
            $("format").innerHTML = "";

            const bestOpt = document.createElement("option");
            bestOpt.value = "best";
            bestOpt.textContent = "Auto Best Quality (MP4 + Audio Merged)";
            $("format").appendChild(bestOpt);

            (data.formats || []).forEach(f => {
                if (f.format_id === "best") return;
                const option = document.createElement("option");
                option.value = f.format_id;
                const res = f.height ? `${f.height}p` : "Audio";
                const audioTag = f.has_video === false ? "Audio Only" : (f.has_audio ? "Video+Audio" : "HD Video (Auto-Audio)");
                option.textContent = `${res} · ${(f.ext || "mp4").toUpperCase()} · ${audioTag}${formatBytes(f.filesize)}`;
                $("format").appendChild(option);
            });
        }

        $("result").classList.remove("hidden");
        $("status").textContent = "Analysis complete. Ready to download.";

    } catch (error) {
        $("status").textContent = "Error: " + error.message;
    } finally {
        $("inspect").disabled = false;
    }
});

$("url").addEventListener("keydown", e => {
    if (e.key === "Enter") {
        e.preventDefault();
        $("inspect").click();
    }
});

function renderPlaylist() {
    $("playlistItems").innerHTML = "";

    playlistEntries.forEach((entry, index) => {
        const row = document.createElement("label");
        row.className = "playlist-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "video-check";
        checkbox.dataset.index = index;
        checkbox.addEventListener("change", updateSelectedCount);

        const title = document.createElement("span");
        title.textContent = (index + 1) + ". " + entry.title;

        row.appendChild(checkbox);
        row.appendChild(title);
        $("playlistItems").appendChild(row);
    });

    $("selectAll").checked = false;
    updateSelectedCount();
}

function updateSelectedCount() {
    const checks = [...document.querySelectorAll(".video-check")];
    const selected = checks.filter(c => c.checked).length;

    $("selectedCount").textContent = selected + " selected";
    $("selectAll").checked = checks.length > 0 && selected === checks.length;
}

$("selectAll").addEventListener("change", () => {
    document.querySelectorAll(".video-check").forEach(c => {
        c.checked = $("selectAll").checked;
    });
    updateSelectedCount();
});

function getFilenameFromHeader(header, fallback) {
    if (!header) return fallback;

    const utf8Match = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
    if (utf8Match) {
        try {
            return decodeURIComponent(utf8Match[1].trim().replace(/^["']|["']$/g, ""));
        } catch (_) {}
    }

    const match = header.match(/filename\s*=\s*"?([^";]+)"?/i);
    if (match) return match[1].trim();

    return fallback;
}

async function downloadOne(url, audio, formatId = "best") {
    const response = await fetch("/api/download", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            url: url,
            format_id: formatId,
            audio: audio
        })
    });

    if (!response.ok) {
        let errText = "Download failed";
        try {
            const error = await response.json();
            errText = error.detail || errText;
        } catch (_) {}
        throw new Error(errText);
    }

    const blob = await response.blob();
    const fallback = audio ? "media.mp3" : "media.mp4";
    const filename = getFilenameFromHeader(
        response.headers.get("Content-Disposition"),
        fallback
    );

    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
}

async function downloadSingle(audio) {
    $("videoDownload").disabled = true;
    $("audioDownload").disabled = true;
    $("status").textContent = audio
        ? "Extracting & converting MP3... Please wait."
        : "Downloading & merging video... Please wait.";

    try {
        await downloadOne(mediaUrl, audio, $("format").value || "best");
        $("status").textContent = "Download completed!";
    } catch (error) {
        $("status").textContent = "Error: " + error.message;
    } finally {
        $("videoDownload").disabled = false;
        $("audioDownload").disabled = false;
    }
}

async function downloadSelected(audio) {
    const selected = [...document.querySelectorAll(".video-check:checked")];

    if (!selected.length) {
        $("status").textContent = "Please select at least one video.";
        return;
    }

    $("downloadSelected").disabled = true;
    $("downloadSelectedAudio").disabled = true;

    let completed = 0;
    const failures = [];

    for (const checkbox of selected) {
        const entry = playlistEntries[Number(checkbox.dataset.index)];

        try {
            $("status").textContent =
                "Downloading " + (completed + 1) + " of " + selected.length +
                ": " + entry.title;

            await downloadOne(entry.url, audio);
            completed++;
            await new Promise(resolve => setTimeout(resolve, 1200));

        } catch (error) {
            failures.push(entry.title + ": " + error.message);
        }
    }

    $("downloadSelected").disabled = false;
    $("downloadSelectedAudio").disabled = false;

    $("status").textContent =
        "Completed: " + completed + " / " + selected.length +
        (failures.length ? " · Failed: " + failures.length : "");

    if (failures.length) {
        console.error("Download errors:", failures);
    }
}

$("videoDownload").addEventListener("click", () => downloadSingle(false));
$("audioDownload").addEventListener("click", () => downloadSingle(true));

$("downloadSelected").addEventListener("click", () => downloadSelected(false));
$("downloadSelectedAudio").addEventListener("click", () => downloadSelected(true));
