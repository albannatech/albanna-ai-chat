// The rules of the microphone.
//
// Pure: no `frappe`, no DOM, `__` is injected as a callback rather than
// read from the window, so this is tested under plain node.  The
// component owns the browser's `SpeechRecognition`; what lives here is
// what a session of it *means* — which words are new, what the composer
// should show while it runs, and what the browser's refusal says in the
// reader's language.

/** How long one dictation may run before it is closed for the reader. */
export const MAX_SESSION_MS = 120000;

/**
 * The words a result event adds.
 *
 * A browser may report the whole list again, with `resultIndex` where
 * the change starts.  A final result is taken once and only once:
 * taking the same final twice repeats the sentence, and then the model
 * answers a question that was asked twice.
 *
 * @param {object} results the event's results, indexed like an array
 * @param {number} resultIndex where the change starts, per the event
 * @param {number} nextFinal the index after the last final already taken
 * @returns {{finals: string[], interim: string, nextFinal: number}} the
 *   new finals, the words still being spoken, and the index to keep
 */
export function readResults(results, resultIndex, nextFinal) {
	const finals = [];
	let interim = "";
	let next = Number(nextFinal) || 0;
	if (!results || !results.length) return { finals, interim, nextFinal: next };

	const from = Math.max(0, Number(resultIndex) || 0, next);
	for (let i = from; i < results.length; i += 1) {
		const result = results[i];
		if (!result) continue;
		const spoken = result[0] && result[0].transcript ? String(result[0].transcript) : "";
		if (result.isFinal) {
			if (spoken) finals.push(spoken);
			next = i + 1;
			// A final clears the interim: the words that were tentative
			// are now spoken, and the trailing chunk starts empty again.
			interim = "";
		} else if (spoken) {
			// The trailing chunk is what is still being spoken.  It is
			// replaced, not appended — the browser reports the whole
			// uncertain tail each time, so concatenating it would double
			// the words.
			interim = spoken;
		}
	}
	return { finals, interim, nextFinal: next };
}

/**
 * The composer's text while a dictation runs.
 *
 * The spoken words are only one of the things in the box.  The reader
 * may have typed alongside them — a correction, a second sentence — and
 * that text is theirs, not the browser's.  So the text already shown is
 * the anchor: whatever they added after it is kept, and what is replaced
 * is only the spoken part.
 *
 * @param {object} parts
 * @param {string} parts.spoken the words so far, finals and interim
 * @param {string} parts.current the composer's text now
 * @param {string} parts.lastEmitted the text this module last produced
 * @returns {string} the text to show
 */
export function mergeTranscript({ spoken, current, lastEmitted } = {}) {
	const words = String(spoken == null ? "" : spoken).trim();
	const text = String(current == null ? "" : current);
	const anchor = String(lastEmitted == null ? "" : lastEmitted);
	// Whatever the reader added to what we last showed them is theirs.  An
	// empty anchor means nothing was shown yet, so everything in the box is
	// theirs.
	const typed = text.startsWith(anchor) ? text.slice(anchor.length).trim() : "";
	if (!words) return typed;
	return typed ? `${words} ${typed}` : words;
}

/**
 * What the browser said, in the reader's language.
 *
 * The codes are the browser's, not ours: `not-allowed` is a permission
 * the reader refused, `no-speech` is silence, `network` is a connection
 * that is not there.  A button that stops being red and says nothing is
 * a button the reader cannot use or diagnose.
 *
 * @param {string} code the browser's error code
 * @param {Function} [translate] the translator, usually `__`
 * @returns {string} the sentence to show, or "" for a deliberate stop
 */
export function voiceErrorText(code, translate) {
	const say = typeof translate === "function" ? translate : (text) => text;
	switch (String(code || "")) {
		case "not-allowed":
		case "service-not-allowed":
			return say(
				"Microphone access was denied. Allow it in your browser to use voice input.",
			);
		case "no-speech":
			return say("No speech was heard.");
		case "audio-capture":
			return say("No microphone was found.");
		case "network":
			return say("Voice input needs a network connection.");
		case "language-not-supported":
			return say("This language is not supported for voice input.");
		case "aborted":
			// The reader closed it.  That is not a failure.
			return "";
		default:
			return say("Voice input failed. Please try again.");
	}
}
