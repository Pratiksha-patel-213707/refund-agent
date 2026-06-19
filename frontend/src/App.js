import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  MessageSquare, LayoutDashboard, Mic, MicOff, Send, Bot, User,
  CheckCircle, XCircle, AlertTriangle, ChevronDown, ChevronRight,
  RefreshCw, Users, Activity, Clock, Shield, Loader, Volume2, VolumeX,
  Zap, FileText, Search, Package
} from "lucide-react";

const API = process.env.REACT_APP_API_URL || "http://localhost:8000";

// ── Helpers ────────────────────────────────────────────────────────────────────
const tierColor = { Platinum: "#8b5cf6", Gold: "#f59e0b", Silver: "#64748b", Bronze: "#b45309" };
const tierBg = { Platinum: "#f5f3ff", Gold: "#fffbeb", Silver: "#f8fafc", Bronze: "#fef3c7" };

function StatusBadge({ text, type }) {
  const styles = {
    approved: { bg: "#dcfce7", color: "#166534", icon: <CheckCircle size={12} /> },
    denied: { bg: "#fee2e2", color: "#991b1b", icon: <XCircle size={12} /> },
    pending: { bg: "#fef9c3", color: "#854d0e", icon: <AlertTriangle size={12} /> },
    tool: { bg: "#eff6ff", color: "#1e40af", icon: <Zap size={12} /> },
    info: { bg: "#f0fdf4", color: "#166534", icon: <Activity size={12} /> },
  };
  const s = styles[type] || styles.info;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: s.bg, color: s.color }}>
      {s.icon} {text}
    </span>
  );
}

// ── Voice Hook ────────────────────────────────────────────────────────────────
function useVoice(onTranscript) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const [error, setError] = useState("");
  const recRef = useRef(null);

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const canUseMicrophone = window.isSecureContext || window.location.hostname === "localhost";
    if (SpeechRecognition && canUseMicrophone) {
      setSupported(true);
      const rec = new SpeechRecognition();
      rec.continuous = false;
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.lang = navigator.language || "en-US";
      rec.onstart = () => {
        setError("");
        setListening(true);
      };
      rec.onresult = (e) => {
        const result = e.results[e.results.length - 1];
        const text = result?.[0]?.transcript?.trim();
        if (text) onTranscript(text);
      };
      rec.onend = () => setListening(false);
      rec.onerror = (event) => {
        setListening(false);
        const errors = {
          "not-allowed": "Microphone permission was denied. Allow microphone access in your browser settings.",
          "service-not-allowed": "Browser speech recognition is blocked. Use Chrome or Edge and allow microphone access.",
          "audio-capture": "No working microphone was found. Check your input device.",
          "no-speech": "No speech was detected. Please try again and speak clearly.",
          network: "The browser speech service could not connect. Check your internet connection.",
          aborted: "Voice input was stopped.",
        };
        setError(errors[event.error] || `Voice recognition failed (${event.error || "unknown error"}).`);
      };
      recRef.current = rec;
    } else if (!canUseMicrophone) {
      setError("Microphone access requires HTTPS or localhost.");
    } else {
      setError("Voice input is not supported by this browser. Use the latest Chrome or Edge.");
    }

    return () => {
      try { recRef.current?.abort(); } catch (_) { /* already stopped */ }
      recRef.current = null;
    };
  }, [onTranscript]);

  const toggle = useCallback(async () => {
    if (!recRef.current) return;
    if (listening) {
      recRef.current.stop();
      return;
    }

    setError("");
    try {
      // Request permission explicitly so denial is visible and retryable.
      if (navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(track => track.stop());
      }
      recRef.current.start();
    } catch (err) {
      setListening(false);
      if (err?.name === "NotAllowedError") {
        setError("Microphone permission was denied. Click the lock icon in the address bar and allow Microphone.");
      } else if (err?.name === "NotFoundError") {
        setError("No microphone was found. Connect or enable an input device.");
      } else {
        setError(`Could not start voice input: ${err?.message || "unknown error"}`);
      }
    }
  }, [listening]);

  return { listening, supported, error, toggle };
}

// ── TTS ───────────────────────────────────────────────────────────────────────
function useTTS() {
  const [speaking, setSpeaking] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const supported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;

  const speak = useCallback((text) => {
    if (!enabled || !supported) return;
    window.speechSynthesis.cancel();
    const clean = text.replace(/[*#`_~]/g, "").substring(0, 400);
    const utt = new SpeechSynthesisUtterance(clean);
    utt.rate = 1.0; utt.pitch = 1.0;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => v.name.includes("Google") || v.name.includes("Samantha"));
    if (preferred) utt.voice = preferred;
    utt.onstart = () => setSpeaking(true);
    utt.onend = () => setSpeaking(false);
    utt.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utt);
  }, [enabled, supported]);

  return { speaking, enabled, setEnabled, speak, supported };
}

// ── Reasoning Log Entry ───────────────────────────────────────────────────────
function LogEntry({ entry, index }) {
  const [open, setOpen] = useState(false);
  const isCall = entry.type === "tool_call";
  const isResult = entry.type === "tool_result";
  const hasDetails = !["agent_response", "final_response"].includes(entry.type);

  const icons = {
    intent: <Search size={14} color="#6366f1" />,
    information_collection: <Package size={14} color="#0f766e" />,
    tool_call: <Zap size={14} color="#3b82f6" />,
    tool_result: <FileText size={14} color="#10b981" />,
    validation_results: <Shield size={14} color="#f59e0b" />,
    final_decision: entry.decision === "APPROVED" ? <CheckCircle size={14} color="#16a34a" /> : <XCircle size={14} color="#dc2626" />,
    agent_response: <MessageSquare size={14} color="#8b5cf6" />,
    final_response: <MessageSquare size={14} color="#8b5cf6" />,
  };
  const labels = {
    intent: "Intent Detection",
    information_collection: "Information Collection",
    tool_call: "Tool Called",
    tool_result: "Tool Output",
    validation_results: "Validation Results",
    final_decision: "Final Decision",
    agent_response: "Agent Response",
    final_response: "Agent Response",
  };
  const colors = {
    intent: "#eef2ff",
    information_collection: "#f0fdfa",
    tool_call: "#eff6ff",
    tool_result: "#f0fdf4",
    validation_results: "#fffbeb",
    final_decision: entry.decision === "APPROVED" ? "#dcfce7" : "#fee2e2",
    agent_response: "#f5f3ff",
    final_response: "#f5f3ff",
  };
  const details = isCall ? entry.args : isResult ? entry.result : entry;

  return (
    <div style={{ borderRadius: 8, border: "1px solid #e5e7eb", overflow: "hidden", marginBottom: 6 }}>
      <div
        onClick={() => hasDetails && setOpen(!open)}
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: colors[entry.type] || "#f9fafb", cursor: hasDetails ? "pointer" : "default", userSelect: "none" }}
      >
        <span style={{ fontSize: 11, color: "#9ca3af", minWidth: 20 }}>#{index + 1}</span>
        {icons[entry.type] || <Activity size={14} color="#64748b" />}
        <span style={{ fontSize: 12, fontWeight: 600, flex: 1 }}>
          {labels[entry.type] || entry.type} {isCall ? `-> ${entry.tool}` : isResult ? `<- ${entry.tool}` : entry.decision ? `: ${entry.decision}` : ""}
        </span>
        <span style={{ fontSize: 10, color: "#9ca3af" }}>{entry.timestamp?.slice(11, 19)}</span>
        {hasDetails && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
      </div>
      {open && hasDetails && (
        <div style={{ padding: "10px 12px", background: "#fff", borderTop: "1px solid #e5e7eb" }}>
          <pre style={{ margin: 0, fontSize: 11, overflowX: "auto", color: "#374151", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {JSON.stringify(details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Chat Message ──────────────────────────────────────────────────────────────
function ChatBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", marginBottom: 16, gap: 10, alignItems: "flex-end" }}>
      {!isUser && (
        <div style={{ width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Bot size={16} color="#fff" />
        </div>
      )}
      <div style={{
        maxWidth: "70%", padding: "12px 16px", borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
        background: isUser ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "#f8fafc",
        color: isUser ? "#fff" : "#1e293b",
        boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
        border: isUser ? "none" : "1px solid #e2e8f0",
        fontSize: 14, lineHeight: 1.6,
      }}>
        <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
        {msg.reasoning_log?.length > 0 && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid rgba(0,0,0,0.1)" }}>
            <span style={{ fontSize: 11, opacity: 0.7 }}>🔧 {msg.reasoning_log.filter(l => l.type === "tool_call").length} tools used</span>
          </div>
        )}
      </div>
      {isUser && (
        <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#e2e8f0", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <User size={16} color="#64748b" />
        </div>
      )}
    </div>
  );
}

// ── Chat Page ─────────────────────────────────────────────────────────────────
function ChatPage({ messages, setMessages, logs, setLogs, sessionId }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const { speak, enabled: ttsEnabled, setEnabled: setTTSEnabled, speaking, supported: ttsSupported } = useTTS();

  const handleTranscript = useCallback((text) => setInput(text), []);
  const { listening, supported: voiceSupported, error: voiceError, toggle: toggleVoice } = useVoice(handleTranscript);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  const send = async (text) => {
    const msg = text || input;
    if (!msg.trim() || loading) return;
    setInput("");

    const userMsg = { role: "user", content: msg };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setLoading(true);

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages.map(m => ({ role: m.role, content: m.content })),
          session_id: sessionId,
        }),
      });
      const data = await res.json();
      const agentMsg = { role: "assistant", content: data.response, reasoning_log: data.reasoning_log || [] };
      setMessages(prev => [...prev, agentMsg]);
      setLogs(prev => [...prev, ...( data.reasoning_log || [])]);
      speak(data.response);
    } catch (err) {
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Connection error. Is the backend running?", reasoning_log: [] }]);
    }
    setLoading(false);
  };

  const quickPrompts = [
    "I'd like a refund ",
    "My headphones arrived broken",
    "I changed my mind about my purchase",
    "Check my refund eligibility for ORD-0000",
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#fff" }}>
      {/* Header */}
      <div style={{ padding: "16px 24px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 12, background: "linear-gradient(135deg,#6366f1,#8b5cf6)" }}>
        <div style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Bot size={22} color="#fff" />
        </div>
        <div>
          <div style={{ fontWeight: 700, color: "#fff", fontSize: 16 }}>ARIA — Refund Agent</div>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.8)" }}>● Online • Powered by Gemini</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={() => setTTSEnabled(!ttsEnabled)} disabled={!ttsSupported} title={ttsSupported ? "Read agent replies aloud" : "Speech output is unsupported in this browser"} style={{ background: "rgba(255,255,255,0.2)", border: "none", borderRadius: 8, padding: "6px 10px", color: "#fff", cursor: ttsSupported ? "pointer" : "not-allowed", opacity: ttsSupported ? 1 : 0.6, display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
            {ttsEnabled && ttsSupported ? <Volume2 size={14} /> : <VolumeX size={14} />} {speaking ? "Speaking..." : ttsEnabled && ttsSupported ? "TTS On" : "TTS Off"}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", padding: "40px 20px" }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🤖</div>
            <h2 style={{ color: "#1e293b", marginBottom: 8 }}>Welcome to ShopEase Support</h2>
            <p style={{ color: "#64748b", marginBottom: 24, maxWidth: 400, margin: "0 auto 24px" }}>
              I'm ARIA, your AI refund specialist. I can process or deny refund requests based on our strict policy.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              {quickPrompts.map((p, i) => (
                <button key={i} onClick={() => send(p)} style={{ background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 20, padding: "8px 16px", fontSize: 13, color: "#475569", cursor: "pointer" }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => <ChatBubble key={i} msg={msg} />)}
        {loading && (
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 16 }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Bot size={16} color="#fff" />
            </div>
            <div style={{ padding: "12px 16px", background: "#f8fafc", borderRadius: "18px 18px 18px 4px", border: "1px solid #e2e8f0" }}>
              <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                {[0, 1, 2].map(i => (
                  <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: "#6366f1", animation: `bounce 1.4s ${i * 0.2}s infinite` }} />
                ))}
                <span style={{ marginLeft: 8, fontSize: 12, color: "#64748b" }}>Analyzing policy...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "16px 24px", borderTop: "1px solid #e2e8f0", background: "#f8fafc" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", background: "#fff", borderRadius: 12, border: "1px solid #e2e8f0", padding: "8px 8px 8px 16px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
            placeholder={listening ? "🎤 Listening..." : "Type your refund request..."}
            style={{ flex: 1, border: "none", outline: "none", fontSize: 14, color: "#1e293b", background: "transparent" }}
          />
          <button onClick={toggleVoice} disabled={!voiceSupported} title={voiceSupported ? (listening ? "Stop listening" : "Speak your refund request") : voiceError} style={{ padding: "8px", borderRadius: 8, border: "none", background: listening ? "#fee2e2" : "#eff6ff", color: listening ? "#dc2626" : "#6366f1", cursor: voiceSupported ? "pointer" : "not-allowed", opacity: voiceSupported ? 1 : 0.45 }}>
            {listening ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
          <button onClick={() => send()} disabled={!input.trim() || loading} style={{ padding: "8px 16px", borderRadius: 8, border: "none", background: input.trim() && !loading ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "#e2e8f0", color: input.trim() && !loading ? "#fff" : "#9ca3af", cursor: input.trim() && !loading ? "pointer" : "default", display: "flex", alignItems: "center", gap: 4, fontWeight: 600, fontSize: 13 }}>
            <Send size={15} /> Send
          </button>
        </div>
        {voiceError && <div role="alert" style={{ marginTop: 7, color: "#b91c1c", fontSize: 12 }}>{voiceError}</div>}
        {listening && <div aria-live="polite" style={{ marginTop: 7, color: "#4f46e5", fontSize: 12 }}>Listening… Speak now. Your transcript will appear in the input box.</div>}
      </div>
    </div>
  );
}

// ── Admin Dashboard ───────────────────────────────────────────────────────────
function AdminPage({ logs, messages }) {
  const [customers, setCustomers] = useState([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetch(`${API}/api/customers`).then(r => r.json()).then(d => setCustomers(d.customers || [])).catch(() => {});
  }, []);

  const toolCalls = logs.filter(l => l.type === "tool_call");
  const approvedCount = logs.filter(l => l.type === "tool_result" && l.result?.eligible === true).length;
  const deniedCount = logs.filter(l => l.type === "tool_result" && l.result?.eligible === false).length;
  const totalInteractions = messages.filter(m => m.role === "user").length;

  const filtered = customers.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.email.toLowerCase().includes(search.toLowerCase()) ||
    c.tier.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: 24, background: "#f8fafc" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1e293b", marginBottom: 6 }}>Admin Dashboard</h1>
      <p style={{ color: "#64748b", marginBottom: 24, fontSize: 14 }}>Real-time agent reasoning and CRM overview</p>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Total Interactions", value: totalInteractions, icon: <MessageSquare size={20} />, color: "#6366f1" },
          { label: "Tool Calls Made", value: toolCalls.length, icon: <Zap size={20} />, color: "#3b82f6" },
          { label: "Refunds Approved", value: approvedCount, icon: <CheckCircle size={20} />, color: "#10b981" },
          { label: "Refunds Denied", value: deniedCount, icon: <XCircle size={20} />, color: "#ef4444" },
        ].map((s, i) => (
          <div key={i} style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e2e8f0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <span style={{ color: "#64748b", fontSize: 13 }}>{s.label}</span>
              <div style={{ color: s.color }}>{s.icon}</div>
            </div>
            <div style={{ fontSize: 32, fontWeight: 700, color: "#1e293b" }}>{s.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* Reasoning Log */}
        <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #e2e8f0", padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <Activity size={18} color="#6366f1" />
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "#1e293b" }}>Agent Reasoning Log</h2>
            <span style={{ marginLeft: "auto", background: "#eff6ff", color: "#3b82f6", fontSize: 11, padding: "2px 8px", borderRadius: 20, fontWeight: 600 }}>{logs.length} events</span>
          </div>
          <div style={{ maxHeight: 400, overflowY: "auto" }}>
            {logs.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40, color: "#94a3b8" }}>
                <Activity size={32} style={{ marginBottom: 8, opacity: 0.3 }} />
                <p style={{ fontSize: 13 }}>No agent activity yet.<br />Start a chat to see reasoning logs.</p>
              </div>
            ) : (
              logs.map((entry, i) => <LogEntry key={i} entry={entry} index={i} />)
            )}
          </div>
        </div>

        {/* CRM Table */}
        <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #e2e8f0", padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <Users size={18} color="#6366f1" />
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "#1e293b" }}>CRM — Customer Profiles</h2>
            <span style={{ marginLeft: "auto", background: "#f0fdf4", color: "#166534", fontSize: 11, padding: "2px 8px", borderRadius: 20, fontWeight: 600 }}>{customers.length} customers</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, background: "#f8fafc", borderRadius: 8, padding: "8px 12px", border: "1px solid #e2e8f0" }}>
            <Search size={14} color="#94a3b8" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search customers..." style={{ border: "none", background: "transparent", outline: "none", fontSize: 13, flex: 1, color: "#1e293b" }} />
          </div>
          <div style={{ maxHeight: 360, overflowY: "auto" }}>
            {filtered.map((c, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: i < filtered.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                <div style={{ width: 36, height: 36, borderRadius: "50%", background: tierBg[c.tier] || "#f1f5f9", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700, color: tierColor[c.tier] || "#64748b", flexShrink: 0 }}>
                  {c.name[0]}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: "#1e293b", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.email}</div>
                </div>
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: tierColor[c.tier], background: tierBg[c.tier], padding: "2px 8px", borderRadius: 20 }}>{c.tier}</span>
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{c.refund_count} refunds</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("chat");
  const [messages, setMessages] = useState([]);
  const [logs, setLogs] = useState([]);
  const sessionId = useRef(`session-${Date.now()}`);

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "'Inter', system-ui, sans-serif", background: "#f8fafc" }}>
      {/* Sidebar */}
      <div style={{ width: 220, background: "#1e1e2e", display: "flex", flexDirection: "column", padding: "24px 12px" }}>
        <div style={{ padding: "0 8px 24px", borderBottom: "1px solid rgba(255,255,255,0.1)", marginBottom: 16 }}>
          <div style={{ fontWeight: 800, color: "#fff", fontSize: 18, letterSpacing: "-0.5px" }}>ShopEase</div>
          <div style={{ fontSize: 11, color: "#6366f1", fontWeight: 600, letterSpacing: 1 }}>SUPPORT AI</div>
        </div>
        {[
          { id: "chat", label: "Customer Chat", icon: <MessageSquare size={18} /> },
          { id: "admin", label: "Admin Dashboard", icon: <LayoutDashboard size={18} /> },
        ].map(item => (
          <button
            key={item.id}
            onClick={() => setPage(item.id)}
            style={{
              display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8,
              background: page === item.id ? "rgba(99,102,241,0.2)" : "transparent",
              color: page === item.id ? "#a5b4fc" : "rgba(255,255,255,0.6)",
              border: page === item.id ? "1px solid rgba(99,102,241,0.3)" : "1px solid transparent",
              cursor: "pointer", fontSize: 13, fontWeight: page === item.id ? 600 : 400,
              marginBottom: 4, textAlign: "left", transition: "all 0.15s",
            }}
          >
            {item.icon} {item.label}
          </button>
        ))}
        <div style={{ marginTop: "auto", padding: "12px 8px", borderTop: "1px solid rgba(255,255,255,0.1)" }}>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", lineHeight: 1.6 }}>
            <div>🤖 Gemini LLM</div>
            <div>🎤 Web Speech API</div>
            <div>🔒 Policy Enforced</div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {page === "chat" ? (
          <ChatPage messages={messages} setMessages={setMessages} logs={logs} setLogs={setLogs} sessionId={sessionId.current} />
        ) : (
          <AdminPage logs={logs} messages={messages} />
        )}
      </div>

      <style>{`
        @keyframes bounce {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-8px); }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 3px; }
      `}</style>
    </div>
  );
}
