// The browser half of the contract with app/server.py.
//
// Answers arrive as a server-sent event stream rather than one JSON response,
// because a question can take a minute of tool rounds and the point of this
// product is that you see which computation ran while it is still running.

/** Raised when the server says the conversation is gone, so the caller can
 *  start a fresh one instead of showing the farmer an error. */
export class SessionExpired extends Error {}

async function readJson(response) {
    try {
        return await response.json();
    } catch {
        return {};
    }
}

export async function fetchHealth() {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('The chatbot server is not responding.');
    return response.json();
}

export async function createSession() {
    const response = await fetch('/api/session', { method: 'POST' });
    if (!response.ok) throw new Error('Could not start a conversation.');
    const { session_id } = await response.json();
    return session_id;
}

/**
 * Ask one question. `onTool(name, args)` fires per tool call as it happens.
 * Resolves with the answer text; rejects with the reason the server gave.
 */
export async function ask(sessionId, question, { onTool, signal } = {}) {
    const response = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, question }),
        signal
    });

    if (!response.ok) {
        const body = await readJson(response);
        if (body.code === 'session_expired') throw new SessionExpired(body.error);
        throw new Error(body.error || `The server returned ${response.status}.`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let answer = '';
    let failure = null;

    // Frames are separated by a blank line; a frame can straddle two chunks,
    // so only whole frames are taken out of the buffer.
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split;
        while ((split = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, split);
            buffer = buffer.slice(split + 2);

            let event = 'message';
            let data = '';
            for (const line of frame.split('\n')) {
                if (line.startsWith('event:')) event = line.slice(6).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
            }
            if (!data) continue;

            let payload;
            try {
                payload = JSON.parse(data);
            } catch {
                continue;
            }

            if (event === 'tool') onTool?.(payload.name, payload.arguments ?? {});
            else if (event === 'answer') answer = payload.content ?? '';
            else if (event === 'error') failure = payload.message;
        }
    }

    if (failure) throw new Error(failure);
    // A stream that ends without either event means the connection dropped
    // mid-answer -- silence would look like an empty reply from the model.
    if (!answer) throw new Error('The connection closed before the answer arrived.');
    return answer;
}
