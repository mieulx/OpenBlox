import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import threading
import time

from website_manager import WebsiteManager
from extractor import ContentExtractor
from kilo_client import KiloClient
from chat_store import ChatStore, ChatSession
from processor import DevProcessor


BG = "#0d1117"
BG2 = "#161b22"
BG3 = "#1c2333"
INPUT_BG = "#0d1117"
FG = "#e6edf3"
FG2 = "#8b949e"
ACCENT = "#58a6ff"
ACCENT2 = "#1f6feb"
BORDER = "#30363d"
USER_BG = "#1f6feb"
USER_FG = "#ffffff"
BOT_BG = "#161b22"
BOT_FG = "#e6edf3"
CODE_BG = "#1c2333"
SEL_BG = "#264a7a"
FONT = ("Segoe UI", 10)
FONT_S = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)


def _setup_styles():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, troughcolor=BG,
                    selectbackground=SEL_BG, selectforeground=FG, font=FONT,
                    borderwidth=0, focusthickness=0)
    style.configure("TFrame", background=BG)
    style.configure("Sidebar.TFrame", background=BG2)
    style.configure("TLabelframe", background=BG2, foreground=FG,
                    bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TButton", background=ACCENT2, foreground=FG,
                    borderwidth=0, padding=(10, 4), font=FONT)
    style.map("TButton", background=[("active", ACCENT), ("disabled", BG3)],
              foreground=[("disabled", FG2)])
    style.configure("Sidebar.TButton", background=BG3, foreground=FG,
                    borderwidth=0, padding=(6, 3), font=FONT_S, anchor="w")
    style.map("Sidebar.TButton", background=[("active", BG2)])
    style.configure("Small.TButton", background=BG3, foreground=FG2,
                    borderwidth=0, padding=(4, 2), font=FONT_S)
    style.map("Small.TButton", background=[("active", ACCENT2)])
    style.configure("TEntry", fieldbackground=INPUT_BG, foreground=FG,
                    bordercolor=BORDER, borderwidth=1, padding=4)
    style.configure("Horizontal.TProgressbar", background=ACCENT,
                    troughcolor=BG)


class _Bubble(tk.Frame):
    def __init__(self, parent, text, is_user, timestamp=""):
        super().__init__(parent, bg=BG)
        self.pack(fill=tk.X, pady=(0, 8))

        inner = tk.Frame(self, bg=USER_BG if is_user else BOT_BG)
        inner.pack(anchor="e" if is_user else "w", padx=(60, 10) if is_user else (10, 60), fill=tk.X)

        label = tk.Label(inner, text=text, bg=inner["bg"],
                         fg=USER_FG if is_user else BOT_FG,
                         font=FONT, justify="left", anchor="w",
                         wraplength=500, padx=12, pady=8)
        label.pack(fill=tk.X)


class RobloxHelperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kilo Roblox Studio Helper")
        self.root.geometry("950x680")
        self.root.minsize(700, 500)
        self.root.configure(bg=BG)
        _setup_styles()

        self.wm = WebsiteManager()
        self.extractor = ContentExtractor(chunk_size=self.wm.search_config["chunk_size"])
        self.dev_proc = DevProcessor(self.wm, self.extractor)
        self.store = ChatStore()
        self.dev_mode = tk.BooleanVar(value=False)

        api_key = self.wm.kilo_config.get("api_key", "")
        model = self.wm.kilo_config.get("model", "kilo-auto/free")
        temp = self.wm.kilo_config.get("temperature", 0.3)
        self.kilo = KiloClient(api_key=api_key, model=model, temperature=temp)

        self._build_menu()
        self._build_ui()
        self._load_chat()

    def _build_menu(self):
        bar = tk.Menu(self.root, bg=BG2, fg=FG, activebackground=ACCENT2,
                      activeforeground=FG, borderwidth=0, relief="flat")
        fm = tk.Menu(bar, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT2,
                     activeforeground=FG, borderwidth=0)
        fm.add_command(label="Settings", command=self._open_settings)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.root.quit)
        bar.add_cascade(label="File", menu=fm)

        hm = tk.Menu(bar, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT2,
                     activeforeground=FG, borderwidth=0)
        hm.add_command(label="About", command=self._show_about)
        bar.add_cascade(label="Help", menu=hm)
        self.root.config(menu=bar)

    def _build_ui(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sidebar = tk.Frame(outer, bg=BG2, width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Chats", bg=BG2, fg=FG2, font=FONT_S,
                 anchor="w").pack(fill=tk.X, padx=10, pady=(10, 2))

        new_btn = tk.Button(sidebar, text="+ New Chat", bg=ACCENT2, fg=FG,
                            activebackground=ACCENT, activeforeground=FG,
                            borderwidth=0, font=FONT, pady=3, cursor="hand2",
                            command=self._new_chat)
        new_btn.pack(fill=tk.X, padx=8, pady=(0, 6))

        self.session_listbox = tk.Listbox(sidebar, bg=BG2, fg=FG,
                                          selectbackground=ACCENT2,
                                          selectforeground=FG, font=FONT,
                                          borderwidth=0, highlightthickness=0,
                                          activestyle="none")
        self.session_listbox.pack(fill=tk.BOTH, expand=True, padx=4)
        self.session_listbox.bind("<<ListboxSelect>>", self._on_session_select)
        self.session_listbox.bind("<Button-3>", self._session_context_menu)

        # Delete button for sessions
        del_btn = tk.Button(sidebar, text="🗑 Delete", bg=BG3, fg=FG2,
                            activebackground="#3d1f1f", activeforeground="#f85149",
                            borderwidth=0, font=FONT_S, pady=2, cursor="hand2",
                            command=self._delete_session)
        del_btn.pack(fill=tk.X, padx=8, pady=(0, 4))

        # Dev mode toggle
        dev_frame = tk.Frame(sidebar, bg=BG2)
        dev_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        dev_cb = tk.Checkbutton(dev_frame, text="Dev Mode", variable=self.dev_mode,
                                bg=BG2, fg=FG2, selectcolor=BG2,
                                activebackground=BG2, activeforeground=FG,
                                font=FONT_S, cursor="hand2")
        dev_cb.pack(side=tk.LEFT)

        # Settings button
        set_btn = tk.Button(sidebar, text="⚙ Settings", bg=BG3, fg=FG2,
                            activebackground=BG2, activeforeground=FG,
                            borderwidth=0, font=FONT_S, pady=2, cursor="hand2",
                            command=self._open_settings)
        set_btn.pack(fill=tk.X, padx=8, pady=(0, 8))

        # Main area
        main = tk.Frame(outer, bg=BG)
        main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Chat display
        chat_frame = tk.Frame(main, bg=BG)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        self.canvas = tk.Canvas(chat_frame, bg=BG, borderwidth=0,
                                highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(chat_frame, orient="vertical",
                                       command=self.canvas.yview)
        self.messages_frame = tk.Frame(self.canvas, bg=BG)

        self.messages_frame.bind("<Configure>",
                                 lambda e: self.canvas.configure(
                                     scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.messages_frame, anchor="nw",
                                   width=chat_frame.winfo_width())
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(1, width=e.width))
        self._bind_mousewheel()

        # Dev mode output (hidden by default)
        self.dev_frame = tk.Frame(main, bg=BG2, height=120)
        self.dev_label = tk.Label(self.dev_frame, text="", bg=BG2, fg=FG2,
                                  font=FONT_MONO, justify="left", anchor="nw",
                                  wraplength=600)
        self.dev_label.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # Input area
        input_frame = tk.Frame(main, bg=BG)
        input_frame.pack(fill=tk.X, padx=6, pady=(4, 6))

        input_row = tk.Frame(input_frame, bg=BG)
        input_row.pack(fill=tk.X)

        self.input_text = tk.Text(input_row, height=3, wrap=tk.WORD,
                                  bg=INPUT_BG, fg=FG, insertbackground=ACCENT,
                                  font=FONT, borderwidth=0, padx=8, pady=6,
                                  highlightthickness=1, highlightbackground=BORDER,
                                  highlightcolor=ACCENT)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Control-Return>", lambda e: self._send())
        self.input_text.bind("<Return>", lambda e: self._send() if not e.state & 0x0001 else None)
        self.input_text.focus()

        self.send_btn = tk.Button(input_row, text="Send", bg=ACCENT2, fg=FG,
                                  activebackground=ACCENT, activeforeground=FG,
                                  borderwidth=0, font=FONT, padx=14, pady=6,
                                  cursor="hand2", command=self._send)
        self.send_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.progress = ttk.Progressbar(input_row, mode="indeterminate", length=60)
        self.progress.pack(side=tk.RIGHT, padx=(0, 6))

        bottom_bar = tk.Frame(main, bg=BG)
        bottom_bar.pack(fill=tk.X, padx=6, pady=(0, 2))
        self.status_label = tk.Label(bottom_bar, text="", bg=BG, fg=FG2,
                                     font=FONT_S, anchor="w")
        self.status_label.pack(side=tk.LEFT)
        api_status = "API: configured" if self.kilo.is_configured() else "API: not configured"
        tk.Label(bottom_bar, text=api_status, bg=BG, fg=FG2,
                 font=FONT_S).pack(side=tk.RIGHT)

    def _bind_mousewheel(self):
        def on_mousewheel(e):
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self.canvas.bind_all("<MouseWheel>", on_mousewheel, add="+")

    def _refresh_session_list(self):
        self.session_listbox.delete(0, tk.END)
        for s in self.store.sessions:
            title = s.title[:28] + ".." if len(s.title) > 30 else s.title
            self.session_listbox.insert(tk.END, title)
        # highlight active
        for i, s in enumerate(self.store.sessions):
            if s.id == self.store.active_id:
                self.session_listbox.selection_clear(0, tk.END)
                self.session_listbox.selection_set(i)
                break

    def _load_chat(self):
        for w in self.messages_frame.winfo_children():
            w.destroy()
        session = self.store.get_active()
        if session:
            for m in session.messages:
                _Bubble(self.messages_frame, m.content, m.role == "user")
        self._scroll_to_bottom()
        self._refresh_session_list()

    def _new_chat(self):
        self.store.new_session()
        self._load_chat()
        self.input_text.focus()

    def _delete_session(self):
        sel = self.session_listbox.curselection()
        if not sel:
            return
        session = self.store.sessions[sel[0]]
        if len(self.store.sessions) <= 1:
            messagebox.showinfo("Info", "Cannot delete the last chat.")
            return
        if messagebox.askyesno("Delete", f"Delete '{session.title}'?"):
            self.store.delete_session(session.id)
            self._load_chat()

    def _on_session_select(self, e):
        sel = self.session_listbox.curselection()
        if not sel:
            return
        session = self.store.sessions[sel[0]]
        self.store.switch_to(session.id)
        self._load_chat()

    def _session_context_menu(self, e):
        idx = self.session_listbox.nearest(e.y)
        if idx < 0:
            return
        self.session_listbox.selection_clear(0, tk.END)
        self.session_listbox.selection_set(idx)

        menu = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG,
                       activebackground=ACCENT2, activeforeground=FG,
                       borderwidth=0)
        menu.add_command(label="Rename", command=lambda: self._rename_session(idx))
        menu.add_command(label="Delete", command=self._delete_session)
        menu.tk_popup(e.x_root, e.y_root)

    def _rename_session(self, idx):
        session = self.store.sessions[idx]
        d = tk.Toplevel(self.root)
        d.title("Rename")
        d.geometry("300x100")
        d.configure(bg=BG)
        d.transient(self.root)
        d.grab_set()
        tk.Label(d, text="New name:", bg=BG, fg=FG, font=FONT).pack(pady=(10, 2))
        e = ttk.Entry(d, width=40)
        e.insert(0, session.title)
        e.pack(pady=4)
        e.select_range(0, tk.END)
        e.focus()

        def save():
            name = e.get().strip() or session.title
            self.store.rename_session(session.id, name)
            self._refresh_session_list()
            d.destroy()

        ttk.Button(d, text="Save", command=save).pack()

    def _send(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            return
        self.input_text.delete("1.0", tk.END)

        session = self.store.get_active()
        session.add_message("user", text)
        if len(session.messages) == 1:
            title = text[:40]
            self.store.rename_session(session.id, title)
        self.store.save_session(session)

        _Bubble(self.messages_frame, text, True)
        self._scroll_to_bottom()
        self._refresh_session_list()

        self.send_btn.config(state=tk.DISABLED)
        self.progress.start()
        self.status_label.config(text="Thinking...")

        thread = threading.Thread(target=self._respond, args=(text,),
                                  daemon=True)
        thread.start()

    def _scroll_to_bottom(self):
        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))

    def _respond(self, text: str):
        try:
            if self.dev_mode.get():
                response = self._respond_dev(text)
            else:
                response = self._respond_normal(text)
        except Exception as e:
            response = f"Error: {e}"

        self.root.after(0, self._show_response, response)

    def _respond_normal(self, text: str) -> str:
        if not self.kilo.is_configured():
            return ("Kilo API key not configured.\n\n"
                    "Go to File > Settings and paste your API key.")

        session = self.store.get_active()
        msgs = [{"role": m.role, "content": m.content}
                for m in session.messages[:-1]]

        return self.kilo.chat(msgs) or "No response from API."

    def _respond_dev(self, text: str) -> str:
        if not self.kilo.is_configured():
            return "API key not configured."

        chunks = self.dev_proc.fetch_for_query(text)
        raw = self.dev_proc.format_raw(chunks)
        self.root.after(0, self._show_dev, raw)

        if not chunks:
            return "No relevant documentation found. Answering without context."

        context = self.dev_proc.build_context(chunks)
        session = self.store.get_active()
        msgs = [{"role": m.role, "content": m.content}
                for m in session.messages[:-1]]

        return self.kilo.chat_with_context(msgs, context)

    def _show_dev(self, text: str):
        self.dev_label.config(text=text[:2000])
        self.dev_frame.pack(fill=tk.X, before=self.dev_frame.master.winfo_children()[0]
                            if self.dev_frame.master else None)

    def _show_response(self, text: str):
        self.progress.stop()
        self.send_btn.config(state=tk.NORMAL)
        self.status_label.config(text="")

        # Hide dev frame if dev mode is off
        if not self.dev_mode.get():
            self.dev_frame.pack_forget()

        session = self.store.get_active()
        if session:
            session.add_message("assistant", text)
            self.store.save_session(session)

        _Bubble(self.messages_frame, text, False)
        self._scroll_to_bottom()

    def _open_settings(self):
        d = tk.Toplevel(self.root)
        d.title("Settings")
        d.geometry("520x340")
        d.configure(bg=BG)
        d.transient(self.root)
        d.grab_set()

        nb = ttk.Notebook(d)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Kilo API tab
        kf = tk.Frame(nb, bg=BG, padx=12, pady=12)
        nb.add(kf, text="Kilo API")

        tk.Label(kf, text="API Key (JWT token):", bg=BG, fg=FG, font=FONT,
                 anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        key_var = tk.StringVar(value=self.kilo.api_key)
        key_entry = ttk.Entry(kf, textvariable=key_var, width=55)
        key_entry.grid(row=0, column=1, pady=4, padx=(8, 0))

        tk.Label(kf, text="Model:", bg=BG, fg=FG, font=FONT,
                 anchor="w").grid(row=1, column=0, sticky="w", pady=4)
        model_var = tk.StringVar(value=self.kilo.model)
        model_entry = ttk.Entry(kf, textvariable=model_var, width=55)
        model_entry.grid(row=1, column=1, pady=4, padx=(8, 0))
        tk.Label(kf, text="Default: kilo-auto/free", bg=BG, fg=FG2,
                 font=FONT_S).grid(row=1, column=2, padx=4)

        tk.Label(kf, text="Temperature:", bg=BG, fg=FG, font=FONT,
                 anchor="w").grid(row=2, column=0, sticky="w", pady=4)
        temp_var = tk.DoubleVar(value=self.kilo.temperature)
        tf = tk.Frame(kf, bg=BG)
        tf.grid(row=2, column=1, sticky="w", pady=4, padx=(8, 0))
        ttk.Scale(tf, from_=0.0, to=1.0, variable=temp_var,
                  orient="horizontal", length=150).pack(side="left")
        tl = tk.Label(tf, text=f"{temp_var.get():.1f}", bg=BG, fg=FG, font=FONT)
        tl.pack(side="left", padx=6)
        # fix scale callback
        def on_temp(v):
            tl.config(text=f"{float(v):.1f}")
        # find the scale widget
        for child in tf.winfo_children():
            if isinstance(child, ttk.Scale):
                child.configure(command=on_temp)
                break

        # Search tab
        sf = tk.Frame(nb, bg=BG, padx=12, pady=12)
        nb.add(sf, text="Search")

        tk.Label(sf, text="Max Chunks:", bg=BG, fg=FG, font=FONT,
                 anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        ch_var = tk.IntVar(value=self.wm.search_config.get("max_chunks", 8))
        ttk.Spinbox(sf, from_=1, to=20, textvariable=ch_var,
                    width=8).grid(row=0, column=1, sticky="w", pady=4, padx=(8, 0))

        tk.Label(sf, text="Chunk Size:", bg=BG, fg=FG, font=FONT,
                 anchor="w").grid(row=1, column=0, sticky="w", pady=4)
        sz_var = tk.IntVar(value=self.wm.search_config.get("chunk_size", 1500))
        ttk.Spinbox(sf, from_=200, to=5000, increment=100,
                    textvariable=sz_var, width=8).grid(row=1, column=1, sticky="w",
                                                       pady=4, padx=(8, 0))

        # Websites tab
        wf = tk.Frame(nb, bg=BG, padx=12, pady=12)
        nb.add(wf, text="Websites")

        wlist = tk.Listbox(wf, bg=INPUT_BG, fg=FG, selectbackground=ACCENT2,
                           selectforeground=FG, font=FONT, borderwidth=0,
                           highlightthickness=0, height=6)
        wlist.pack(fill=tk.BOTH, expand=True)
        for w in self.wm.websites:
            dot = "●" if w.enabled else "○"
            wlist.insert(tk.END, f" {dot} {w.name}")

        def toggle_web():
            sel = wlist.curselection()
            if sel:
                self.wm.toggle_website(sel[0])
                wlist.delete(0, tk.END)
                for w in self.wm.websites:
                    dot = "●" if w.enabled else "○"
                    wlist.insert(tk.END, f" {dot} {w.name}")

        tk.Button(wf, text="Toggle", bg=BG3, fg=FG, activebackground=ACCENT2,
                  activeforeground=FG, borderwidth=0, font=FONT_S, pady=2,
                  cursor="hand2", command=toggle_web).pack(pady=(4, 0))

        # Buttons
        btn_row = tk.Frame(d, bg=BG)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        def test():
            k = KiloClient(api_key=key_var.get().strip(),
                           model=model_var.get().strip())
            ok, msg = k.test()
            messagebox.showinfo("Connection Test", msg, parent=d)

        def save():
            self.kilo.api_key = key_var.get().strip()
            self.kilo.model = model_var.get().strip()
            self.kilo.temperature = round(temp_var.get(), 1)
            self.wm.update_kilo_config(
                api_key=self.kilo.api_key,
                endpoint="https://api.kilo.ai/api/gateway/chat/completions",
                model=self.kilo.model,
                temperature=self.kilo.temperature,
            )
            self.wm.update_search_config(
                max_chunks=ch_var.get(),
                chunk_size=sz_var.get(),
            )
            self.extractor.chunk_size = sz_var.get()
            self._update_status_bar()
            d.destroy()

        ttk.Button(btn_row, text="Test", command=test).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=d.destroy).pack(side="right", padx=(5, 0))
        ttk.Button(btn_row, text="Save", command=save).pack(side="right")

    def _update_status_bar(self):
        for w in self.root.winfo_children():
            pass

    def _show_about(self):
        messagebox.showinfo(
            "About",
            "Kilo Roblox Studio Helper\n\n"
            "Chat with Roblox docs using Kilo's free AI.\n"
            "Python + Tkinter + Kilo API"
        )
