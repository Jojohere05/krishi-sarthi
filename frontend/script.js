// Frontend logic for Krishi Saarthi web app
// Handles microphone recording, calls /api/voice-audio,
// and updates the Hindi UI for rural users.

let mediaRecorder = null;
let recordedChunks = [];
let currentState = {}; // conversation state from backend
let currentRole = "consumer"; // default role
let lastAudioUrl = null;

const recordBtn = document.getElementById("record-btn");
const stopBtn = document.getElementById("stop-btn");
const replayBtn = document.getElementById("replay-btn");
const userTextEl = document.getElementById("user-text");
const botTextEl = document.getElementById("bot-text");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const convWindow = document.getElementById("conversation-window");
const roleToggle = document.getElementById("role-toggle");
const landingScreen = document.getElementById("landing-screen");
const assistantScreen = document.getElementById("assistant-screen");
const startVendorBtn = document.getElementById("start-vendor");
const startConsumerBtn = document.getElementById("start-consumer");

function setStatus(mode, text) {
	statusDot.classList.remove("idle", "recording", "thinking");
	statusDot.classList.add(mode);
	statusText.textContent = text;
}

function addBubble(text, type) {
	const div = document.createElement("div");
	div.className = `bubble ${type === "user" ? "bubble-user" : "bubble-system"}`;
	div.innerHTML = `<p>${text}</p>`;
	convWindow.appendChild(div);
	convWindow.scrollTop = convWindow.scrollHeight;
}

function resetRecording() {
	recordedChunks = [];
	if (mediaRecorder) {
		mediaRecorder.ondataavailable = null;
		mediaRecorder.onstop = null;
	}
}

function enterAssistantScreen(role) {
	currentRole = role;
	currentState = {};
	if (landingScreen) landingScreen.classList.add("hidden");
	if (assistantScreen) assistantScreen.classList.remove("hidden");

	// Update role toggle buttons
	if (roleToggle) {
		const buttons = roleToggle.querySelectorAll(".role-btn");
		buttons.forEach((b) => {
			const r = b.getAttribute("data-role");
			if (r === role) b.classList.add("active");
			else b.classList.remove("active");
		});
	}

	const roleLabel = role === "vendor" ? "विक्रेता" : "ग्राहक";
	addBubble(`नमस्ते! आप अभी ${roleLabel} के रूप में बात कर रहे हैं। नीचे बटन दबाकर बोलिए।`, "system");
	setStatus("idle", "तैयार है। नीचे बटन दबाकर बोलिए।");
}

async function startRecording() {
	try {
		const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		recordedChunks = [];
		mediaRecorder = new MediaRecorder(stream);

		mediaRecorder.ondataavailable = (e) => {
			if (e.data.size > 0) {
				recordedChunks.push(e.data);
			}
		};

		mediaRecorder.onstop = () => {
			const blob = new Blob(recordedChunks, { type: "audio/webm" });
			sendAudioToBackend(blob);
			stream.getTracks().forEach((t) => t.stop());
		};

		mediaRecorder.start();
		setStatus("recording", "रिकॉर्ड हो रहा है... बोलते रहिए, फिर रोकें।");
		recordBtn.disabled = true;
		stopBtn.classList.remove("hidden");
	} catch (err) {
		console.error("Mic error", err);
		alert("माइक नहीं चल पाया। कृपया ब्राउज़र को माइक की अनुमति दें।");
	}
}

function stopRecording() {
	if (mediaRecorder && mediaRecorder.state === "recording") {
		mediaRecorder.stop();
		stopBtn.classList.add("hidden");
		setStatus("thinking", "सोच रहा हूँ, कृपया थोड़ी देर रुकिए...");
	}
}

async function sendAudioToBackend(blob) {
	try {
		const form = new FormData();
		const userId = 1; // simple demo; replace with real user id

		form.append("user_id", String(userId));
		form.append("role", currentRole);
		form.append("state", JSON.stringify(currentState || {}));
		form.append("language", "hi");
		form.append("audio_file", new File([blob], "voice.webm", { type: "audio/webm" }));

		const res = await fetch("/api/voice-audio", {
			method: "POST",
			body: form,
		});

		if (!res.ok) {
			throw new Error("Server error " + res.status);
		}

		const data = await res.json();

		const replyText = data.reply_text || "";
		const nextState = data.next_state || {};
		const userText = data.user_text || "";

		// Show recognized Hindi text from STT
		userTextEl.classList.remove("placeholder");
		userTextEl.textContent = userText || "(आपकी आवाज़ प्राप्त हो गई है)";
		botTextEl.classList.remove("placeholder");
		botTextEl.textContent = replyText || "कोई जवाब नहीं मिला";

		addBubble(userText || "(आपकी आवाज़)", "user");
		addBubble(replyText || "कोई जवाब नहीं मिला", "system");

		currentState = nextState;
		setStatus("idle", "तैयार है। फिर से नीचे बटन दबाकर बोलिए।");

		// Handle audio playback
		if (lastAudioUrl) {
			URL.revokeObjectURL(lastAudioUrl);
			lastAudioUrl = null;
		}

		if (data.audio_base64) {
			const audioBytes = Uint8Array.from(atob(data.audio_base64), (c) => c.charCodeAt(0));
			const audioBlob = new Blob([audioBytes], { type: "audio/mpeg" });
			lastAudioUrl = URL.createObjectURL(audioBlob);
			const audio = new Audio(lastAudioUrl);
			audio.play();
			replayBtn.disabled = false;
		} else {
			replayBtn.disabled = true;
		}
	} catch (err) {
		console.error(err);
		setStatus("idle", "कुछ दिक्कत आई। दोबारा कोशिश करें।");
		alert("सर्वर से कनेक्शन में दिक्कत आई। बाद में फिर कोशिश करें।");
	} finally {
		recordBtn.disabled = false;
		resetRecording();
	}
}

// Role toggle (ग्राहक ↔ विक्रेता)
roleToggle.addEventListener("click", (e) => {
	const btn = e.target.closest(".role-btn");
	if (!btn) return;
	const role = btn.getAttribute("data-role");
	if (!role) return;

	currentRole = role;
	// Clear state when changing role, to avoid confusion
	currentState = {};

	document.querySelectorAll(".role-btn").forEach((b) => b.classList.remove("active"));
	btn.classList.add("active");

	const roleLabel = role === "vendor" ? "विक्रेता" : "ग्राहक";
	addBubble(`आप अभी ${roleLabel} मोड में हैं। नीचे बटन दबाकर बोलिए।`, "system");
});

// Landing choices
if (startVendorBtn) {
	startVendorBtn.addEventListener("click", (e) => {
		e.preventDefault();
		enterAssistantScreen("vendor");
	});
}

if (startConsumerBtn) {
	startConsumerBtn.addEventListener("click", (e) => {
		e.preventDefault();
		enterAssistantScreen("consumer");
	});
}

recordBtn.addEventListener("click", () => {
	startRecording();
});

stopBtn.addEventListener("click", () => {
	stopRecording();
});

replayBtn.addEventListener("click", () => {
	if (!lastAudioUrl) return;
	const audio = new Audio(lastAudioUrl);
	audio.play();
});

// Initial status
setStatus("idle", "तैयार है। पहले ऊपर से अपनी भूमिका चुनिए।");

