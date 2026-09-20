/*
 * trk_keyboard.c - TechReader native keyboard layer implementation.
 *
 * Installs a WH_KEYBOARD_LL hook on a dedicated message-pumping thread and
 * describes every low-level keyboard event through the caller's sink.
 * The hook never swallows keys (always CallNextHookEx); injected events are
 * flagged, not filtered, so the command layer above can decide what to do.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "trk_keyboards.h"

#include <stdio.h>
#include <string.h>

/* --- shared state (guarded by g_lock) ----------------------------------- */

static INIT_ONCE            g_once = INIT_ONCE_STATIC_INIT;
static CRITICAL_SECTION     g_lock;
static HANDLE               g_started;      /* manual-reset start/ready event */

static volatile LONG        g_running;      /* hook live and delivering       */
static HHOOK                g_hook;         /* the WH_KEYBOARD_LL hook        */
static HANDLE               g_thread;       /* hook thread handle             */
static DWORD                g_hook_thread_id;
static LONG                 g_hook_failed;  /* SetWindowsHookEx failed        */
static TrkKeyboardSink      g_sink;
static void                *g_user_context;

static BOOL CALLBACK trk_once_init(PINIT_ONCE once, PVOID param, PVOID *ctx)
{
    (void)once; (void)param; (void)ctx;
    InitializeCriticalSection(&g_lock);
    g_started = CreateEventW(NULL, TRUE, FALSE, NULL);
    return (g_started != NULL);
}

static void trk_ensure_init(void)
{
    InitOnceExecuteOnce(&g_once, trk_once_init, NULL, NULL);
}

/* --- event description --------------------------------------------------- */

/* Map a KBDLLHOOKSTRUCT into the public TrkKeyboardEvent. Derives the event
 * type from the struct itself (LLKHF_UP, LLKHF_ALTDOWN, VK_F10) so the same
 * mapping is exercised identically by the live hook and by tests.           */
TRK_KEYBOARD_API void trk_keyboard_describe(const void *llhook_struct,
                                            TrkKeyboardEvent *out_event)
{
    const KBDLLHOOKSTRUCT *k = (const KBDLLHOOKSTRUCT *)llhook_struct;
    uint32_t flags = 0;
    uint32_t mods = 0;
    int is_up, is_sys;
    uint32_t event_type;

    if (out_event == NULL || llhook_struct == NULL) {
        return;
    }

    is_up  = (k->flags & LLKHF_UP) ? 1 : 0;
    is_sys = ((k->flags & LLKHF_ALTDOWN) || k->vkCode == VK_F10) ? 1 : 0;

    if (is_up) {
        event_type = is_sys ? TRK_SYS_KEY_UP : TRK_KEY_UP;
    } else {
        event_type = is_sys ? TRK_SYS_KEY_DOWN : TRK_KEY_DOWN;
    }

    if (k->flags & LLKHF_EXTENDED)           flags |= TRK_FLAG_EXTENDED;
    if (k->flags & LLKHF_INJECTED)           flags |= TRK_FLAG_INJECTED;
    if (k->flags & LLKHF_LOWER_IL_INJECTED)  flags |= TRK_FLAG_LOWER_IL_INJECTED;
    if (k->flags & LLKHF_ALTDOWN)            flags |= TRK_FLAG_ALT_DOWN;
    if (k->flags & LLKHF_UP)                 flags |= TRK_FLAG_TRANSITION;

    /* Physical modifier state. GetAsyncKeyState reflects other threads'
     * view; the event's own modifier is forced on for key-down and off for
     * key-up so the description never contradicts the event itself.       */
    if (GetAsyncKeyState(VK_LCONTROL) & 0x8000) mods |= TRK_MOD_LCTRL;
    if (GetAsyncKeyState(VK_RCONTROL) & 0x8000) mods |= TRK_MOD_RCTRL;
    if (GetAsyncKeyState(VK_LSHIFT)  & 0x8000) mods |= TRK_MOD_LSHIFT;
    if (GetAsyncKeyState(VK_RSHIFT)  & 0x8000) mods |= TRK_MOD_RSHIFT;
    if (GetAsyncKeyState(VK_LMENU)   & 0x8000) mods |= TRK_MOD_LALT;
    if (GetAsyncKeyState(VK_RMENU)   & 0x8000) mods |= TRK_MOD_RALT;
    if (GetAsyncKeyState(VK_LWIN)    & 0x8000) mods |= TRK_MOD_LWIN;
    if (GetAsyncKeyState(VK_RWIN)    & 0x8000) mods |= TRK_MOD_RWIN;
    if (GetAsyncKeyState(VK_CAPITAL) & 0x8000) mods |= TRK_MOD_CAPS;
    if (GetAsyncKeyState(VK_NUMLOCK) & 0x8000) mods |= TRK_MOD_NUM;

    switch (k->vkCode) {
    case VK_LCONTROL: if (is_up) mods &= ~(uint32_t)TRK_MOD_LCTRL; else mods |= TRK_MOD_LCTRL; break;
    case VK_RCONTROL: if (is_up) mods &= ~(uint32_t)TRK_MOD_RCTRL; else mods |= TRK_MOD_RCTRL; break;
    case VK_LSHIFT:   if (is_up) mods &= ~(uint32_t)TRK_MOD_LSHIFT; else mods |= TRK_MOD_LSHIFT; break;
    case VK_RSHIFT:   if (is_up) mods &= ~(uint32_t)TRK_MOD_RSHIFT; else mods |= TRK_MOD_RSHIFT; break;
    case VK_LMENU:    if (is_up) mods &= ~(uint32_t)TRK_MOD_LALT; else mods |= TRK_MOD_LALT; break;
    case VK_RMENU:    if (is_up) mods &= ~(uint32_t)TRK_MOD_RALT; else mods |= TRK_MOD_RALT; break;
    case VK_LWIN:     if (is_up) mods &= ~(uint32_t)TRK_MOD_LWIN; else mods |= TRK_MOD_LWIN; break;
    case VK_RWIN:     if (is_up) mods &= ~(uint32_t)TRK_MOD_RWIN; else mods |= TRK_MOD_RWIN; break;
    case VK_CAPITAL:  if (is_up) mods &= ~(uint32_t)TRK_MOD_CAPS; else mods |= TRK_MOD_CAPS; break;
    case VK_NUMLOCK:  if (is_up) mods &= ~(uint32_t)TRK_MOD_NUM;  else mods |= TRK_MOD_NUM;  break;
    default: break;
    }

    /* Keyboard toggle lamps (Caps Lock / Num Lock on?). GetKeyState is the
     * synchronous toggle state, which is what matters here.               */
    if (GetKeyState(VK_CAPITAL) & 1) mods |= TRK_MOD_CAPS_ON;
    if (GetKeyState(VK_NUMLOCK) & 1) mods |= TRK_MOD_NUM_ON;

    out_event->event_type    = event_type;
    out_event->vk            = (uint32_t)k->vkCode;
    out_event->scan_code     = (uint32_t)k->scanCode;
    out_event->flags         = flags;
    out_event->time_ms       = (uint64_t)GetTickCount64();
    out_event->modifier_state = mods;
    out_event->reserved      = 0;
}

/* --- hook thread ---------------------------------------------------------- */

static LRESULT CALLBACK trk_ll_hook_proc(int code, WPARAM wparam, LPARAM lparam)
{
    if (code == HC_ACTION) {
        TrkKeyboardEvent ev;
        TrkKeyboardSink sink;
        void *ctx;

        /* Snapshot the sink under the lock so stop() can silence delivery
         * before we describe/invoke.                                        */
        EnterCriticalSection(&g_lock);
        sink = g_running ? g_sink : NULL;
        ctx = g_user_context;
        LeaveCriticalSection(&g_lock);

        if (sink != NULL) {
            trk_keyboard_describe((const void *)lparam, &ev);
            (void)sink(&ev, ctx);   /* return value reserved, ignored */
        }
    }
    /* TechReader only observes the keyboard; never swallow anything. */
    return CallNextHookEx(NULL, code, wparam, lparam);
}

static DWORD WINAPI trk_hook_thread(LPVOID arg)
{
    MSG msg;

    (void)arg;
    g_hook_thread_id = GetCurrentThreadId();

    /* Force message-queue creation so PostThreadMessage from stop() cannot
     * race with this thread's first pump.                                  */
    PeekMessageW(&msg, NULL, WM_USER, WM_USER, PM_NOREMOVE);

    g_hook = SetWindowsHookExW(WH_KEYBOARD_LL, trk_ll_hook_proc,
                               GetModuleHandleW(NULL), 0);
    if (g_hook == NULL) {
        g_hook_failed = 1;
        SetEvent(g_started);
        return 0;
    }

    g_running = 1;
    SetEvent(g_started);

    /* Pump until WM_QUIT. A low-level hook only works while this thread
     * keeps pumping messages.                                              */
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        /* nothing to dispatch: the hook uses our callback directly */
    }

    EnterCriticalSection(&g_lock);
    g_running = 0;
    g_sink = NULL;
    if (g_hook != NULL) {
        UnhookWindowsHookEx(g_hook);
        g_hook = NULL;
    }
    LeaveCriticalSection(&g_lock);
    return 0;
}

/* --- lifecycle ------------------------------------------------------------ */

TRK_KEYBOARD_API int trk_keyboard_start(TrkKeyboardSink sink, void *user_context)
{
    int result = TRK_OK;

    trk_ensure_init();
    if (sink == NULL) {
        return TRK_ERR_INVALID_ARG;
    }
    if (g_started == NULL) {
        return TRK_ERR_HOOK_FAILED;
    }

    EnterCriticalSection(&g_lock);
    if (g_running) {
        LeaveCriticalSection(&g_lock);
        return TRK_ERR_ALREADY_RUNNING;
    }
    g_sink = sink;
    g_user_context = user_context;
    g_hook_failed = 0;
    LeaveCriticalSection(&g_lock);

    ResetEvent(g_started);
    g_thread = CreateThread(NULL, 0, trk_hook_thread, NULL, 0, NULL);
    if (g_thread == NULL) {
        EnterCriticalSection(&g_lock);
        g_sink = NULL;
        LeaveCriticalSection(&g_lock);
        return TRK_ERR_HOOK_FAILED;
    }

    if (WaitForSingleObject(g_started, 5000) != WAIT_OBJECT_0) {
        trk_keyboard_stop();
        result = TRK_ERR_TIMEOUT;
    } else if (g_hook_failed) {
        trk_keyboard_stop();
        result = TRK_ERR_HOOK_FAILED;
    }

    return result;
}

TRK_KEYBOARD_API void trk_keyboard_stop(void)
{
    HANDLE thread;

    trk_ensure_init();

    EnterCriticalSection(&g_lock);
    if (!g_running && g_thread == NULL) {
        LeaveCriticalSection(&g_lock);
        return;
    }
    /* Silence delivery first: the hook proc checks g_running under the
     * lock before invoking the sink.                                       */
    g_running = 0;
    g_sink = NULL;
    thread = g_thread;
    LeaveCriticalSection(&g_lock);

    if (g_hook_thread_id != 0) {
        PostThreadMessageW(g_hook_thread_id, WM_QUIT, 0, 0);
    }
    if (thread != NULL) {
        if (WaitForSingleObject(thread, 5000) == WAIT_OBJECT_0) {
            /* the thread unhooked itself and is gone */
        }
        CloseHandle(thread);
    }

    EnterCriticalSection(&g_lock);
    g_thread = NULL;
    g_hook_thread_id = 0;
    LeaveCriticalSection(&g_lock);
}

TRK_KEYBOARD_API int trk_keyboard_is_running(void)
{
    int running;
    trk_ensure_init();
    EnterCriticalSection(&g_lock);
    running = g_running ? 1 : 0;
    LeaveCriticalSection(&g_lock);
    return running;
}
