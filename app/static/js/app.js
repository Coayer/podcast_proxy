// Wait for the DOM to be fully loaded before running the script
document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Element References ---
    const feedTypeSelect = document.getElementById("feed-type");
    const podcastInput = document.getElementById("podcast-input");
    const youtubeInput = document.getElementById("youtube-input");
    const podcastUrlInput = document.getElementById("podcast-url");
    const youtubeChannelInput = document.getElementById("youtube-channel");
    const generateBtn = document.getElementById("generate-btn");
    const copyBtn = document.getElementById("copy-btn");
    const resultOutput = document.getElementById("converted-feed-url");
    const notification = document.getElementById('notification');

    // --- Initial State & Placeholder ---
    resultOutput.textContent = "Your generated URL will appear here...";
    resultOutput.style.opacity = '0.5';

    // --- Event Listeners ---
    feedTypeSelect.addEventListener('change', toggleInputFields);
    generateBtn.addEventListener('click', generateFeedUrl);
    copyBtn.addEventListener('click', copyToClipboard);

    // --- Functions ---
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
        let inputUrl = '';
        let rawInput = '';

        // 1. Validate Input
        if (feedType === "podcast") {
            rawInput = podcastUrlInput.value.trim();
            if (!rawInput) {
                showNotification("Please enter a Podcast Feed URL.", true);
                return;
            }
            // More robustly remove the protocol
            inputUrl = rawInput.replace(/^(https?:\/\/)/, '');
        } else {
            rawInput = youtubeChannelInput.value.trim();
            if (!rawInput) {
                showNotification("Please enter a YouTube Channel ID.", true);
                return;
            }
            inputUrl = `youtube/${rawInput}`;
        }

        // 2. Generate the URL
        const { protocol, hostname, port } = window.location;
        const rssPath = `/feed/${inputUrl}`;
        const feedUrl = port
            ? `${protocol}//${hostname}:${port}${rssPath}`
            : `${protocol}//${hostname}${rssPath}`;

        // 3. Display the result
        resultOutput.textContent = feedUrl;
        resultOutput.style.opacity = '1';
        copyBtn.style.display = 'inline-block';
    }

    function copyToClipboard() {
        const feedUrl = resultOutput.textContent;
        // Avoid copying the placeholder text
        if (feedUrl.startsWith('http')) {
            navigator.clipboard.writeText(feedUrl).then(() => {
                showNotification("URL copied to clipboard!");
            }).catch(err => {
                showNotification("Failed to copy URL.", true);
                console.error('Error copying to clipboard: ', err);
            });
        }
    }

    function showNotification(message, isError = false) {
        notification.textContent = message;
        // Use CSS variables to style the error state
        notification.style.backgroundColor = isError ? 'var(--error-color)' : 'var(--success-color)';
        notification.classList.add('show');
        setTimeout(() => {
            notification.classList.remove('show');
        }, 3000);
    }
});