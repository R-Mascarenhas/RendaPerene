// Open synchronously on the user's actual click, then navigate when OAuth is ready.
export default function(component) {
    const {data, setTriggerValue} = component;
    const states = window.rendaPereneOAuthPopups ??= new Map();
    const state = states.get(data.session) ?? {popup: null, requested: false, url: "", sequence: 0};
    states.set(data.session, state);
    const report = event => {
        const sequence = ++state.sequence;
        // Let Streamlit's original button click reach Python before the diagnostic event.
        setTimeout(() => setTriggerValue?.("popup_event", {event, sequence}), 0);
    };

    const close = () => {
        if (state.popup) {
            try { state.popup.close(); } catch (_) { /* Browser policy may sever the reference. */ }
        }
        state.popup = null;
        state.requested = false;
        state.url = "";
    };

    const onClick = event => {
        const button = event.target.closest?.("button");
        if (!data.enabled || !button || button.disabled ||
            button.textContent.trim() !== "Conectar ao Google") return;
        close();
        state.requested = true;
        state.completed = data.completed ?? 0;
        state.popup = window.open("about:blank", "_blank", "popup=yes,width=520,height=720");
        report(state.popup ? "opened" : "blocked");
        if (state.popup) {
            state.popup.opener = null;
            state.popup.document.title = "Conectar ao Google — RendaPerene";
            state.popup.document.body.textContent = "Preparando a conexão com o Google…";
        }
    };

    if (state.listener) document.removeEventListener("click", state.listener, true);
    state.listener = onClick;
    document.addEventListener("click", onClick, true);
    if (state.requested && data.url && state.url !== data.url) {
        const url = new URL(data.url);
        if (url.protocol === "https:" && url.host === "accounts.google.com") {
            if (state.popup && !state.popup.closed) {
                try {
                    state.popup.location.replace(url.href);
                    report("navigated");
                } catch (_) { report("navigation_failed"); }
            } else {
                report("unavailable");
            }
            state.url = data.url;
        }
    }
    if (state.requested && (data.completed ?? 0) > state.completed) {
        report("finished");
        close();
    }
    return () => {
        document.removeEventListener("click", onClick, true);
        if (state.listener === onClick) state.listener = null;
    };
}
