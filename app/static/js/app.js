// DISCLOSURE: vibe coded file (and html+css)
document.addEventListener("DOMContentLoaded", () => {
    const feedTypeSelect = document.getElementById("feed-type");
    const podcastInput = document.getElementById("podcast-input");
    const youtubeInput = document.getElementById("youtube-input");
    const podcastUrlInput = document.getElementById("podcast-url");
    const youtubeChannelInput = document.getElementById("youtube-channel");
    const generateBtn = document.getElementById("generate-btn");
    const copyBtn = document.getElementById("copy-btn");
    const resultOutput = document.getElementById("converted-feed-url");
    const notification = document.getElementById("notification");

    resultOutput.textContent = "Your generated URL will appear here...";
    resultOutput.style.opacity = "0.5";

    feedTypeSelect.addEventListener("change", toggleInputFields);
    generateBtn.addEventListener("click", generateFeedUrl);
    copyBtn.addEventListener("click", copyToClipboard);

    function toggleInputFields() {
        if (feedTypeSelect.value === "podcast") {
            podcastInput.style.display = "block";
            youtubeInput.style.display = "none";
        } else {
            podcastInput.style.display = "none";
            youtubeInput.style.display = "block";
        }
    }

    function generateFeedUrl() {
        const feedType = feedTypeSelect.value;
        let inputUrl = "";
        let rawInput = "";

        if (feedType === "podcast") {
            rawInput = podcastUrlInput.value.trim();
            if (!rawInput) {
                showNotification("Please enter a Podcast Feed URL.", true);
                return;
            }

            inputUrl = rawInput.replace(/^(https?:\/\/)/, "");
        } else {
            rawInput = youtubeChannelInput.value.trim();
            if (!rawInput) {
                showNotification("Please enter a YouTube Channel ID.", true);
                return;
            }
            inputUrl = `youtube/${rawInput}`;
        }

        const { protocol, hostname, port } = window.location;
        const rssPath = `/feed/${inputUrl}`;
        const feedUrl = port
            ? `${protocol}//${hostname}:${port}${rssPath}`
            : `${protocol}//${hostname}${rssPath}`;

        resultOutput.textContent = feedUrl;
        resultOutput.style.opacity = "1";
        copyBtn.style.display = "inline-block";
    }

    function copyToClipboard() {
        const feedUrl = resultOutput.textContent;

        if (feedUrl.startsWith("http")) {
            navigator.clipboard
                .writeText(feedUrl)
                .then(() => {
                    showNotification("URL copied to clipboard!");
                })
                .catch((err) => {
                    showNotification("Failed to copy URL.", true);
                    console.error("Error copying to clipboard: ", err);
                });
        }
    }

    function showNotification(message, isError = false) {
        notification.textContent = message;

        notification.style.backgroundColor = isError
            ? "var(--error-color)"
            : "var(--success-color)";
        notification.classList.add("show");
        setTimeout(() => {
            notification.classList.remove("show");
        }, 3000);
    }
});
