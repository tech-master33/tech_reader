/*
 * test_sink.c - Self-test for the TechReader native keyboard layer.
 *
 * Part 1 drives trk_keyboard_describe() with synthetic KBDLLHOOKSTRUCT
 * records (no hook, no user input involved). Part 2 runs the real hook and
 * injects a single harmless F24 tap via SendInput to prove events reach the
 * sink with the injected flag set (no feedback filtering in C, flagging
 * only) and that delivery stops after trk_keyboard_stop().
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

#include "trk_keyboards.h"

static int g_checks = 0;
static int g_failures = 0;

#define CHECK(cond, name)                                             \
    do {                                                              \
        g_checks++;                                                   \
        if (cond) {                                                   \
            printf("  ok   %s\n", name);                              \
        } else {                                                      \
            g_failures++;                                             \
            printf("  FAIL %s\n", name);                              \
        }                                                             \
    } while (0)

static KBDLLHOOKSTRUCT make_ll(DWORD vk, DWORD scan, DWORD flags)
{
    KBDLLHOOKSTRUCT k;
    memset(&k, 0, sizeof(k));
    k.vkCode = vk;
    k.scanCode = scan;
    k.flags = flags;
    return k;
}

static void test_describe(void)
{
    TrkKeyboardEvent ev;

    printf("part 1: describe() on synthetic records\n");

    /* Plain 'A' key down */
    memset(&ev, 0xAA, sizeof(ev));
    {
        KBDLLHOOKSTRUCT k = make_ll('A', 0x1E, 0);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK(ev.event_type == TRK_KEY_DOWN, "A down -> TRK_KEY_DOWN");
    CHECK(ev.vk == 'A' && ev.scan_code == 0x1E, "A down -> vk/scan passed through");
    CHECK((ev.flags & TRK_FLAG_TRANSITION) == 0, "A down -> no transition flag");
    CHECK(ev.reserved == 0, "A down -> reserved zeroed");

    /* Plain 'A' key up */
    {
        KBDLLHOOKSTRUCT k = make_ll('A', 0x1E, LLKHF_UP);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK(ev.event_type == TRK_KEY_UP, "A up -> TRK_KEY_UP");
    CHECK((ev.flags & TRK_FLAG_TRANSITION) != 0, "A up -> transition flag");

    /* Injected event keeps the injected flag */
    {
        KBDLLHOOKSTRUCT k = make_ll('B', 0x30, LLKHF_INJECTED);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK((ev.flags & TRK_FLAG_INJECTED) != 0, "injected -> TRK_FLAG_INJECTED");
    CHECK(ev.event_type == TRK_KEY_DOWN, "injected B -> TRK_KEY_DOWN");

    /* Alt+Tab: syskeydown via LLKHF_ALTDOWN */
    {
        KBDLLHOOKSTRUCT k = make_ll(VK_TAB, 0x0F, LLKHF_ALTDOWN);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK(ev.event_type == TRK_SYS_KEY_DOWN, "alt+tab -> TRK_SYS_KEY_DOWN");
    CHECK((ev.flags & TRK_FLAG_ALT_DOWN) != 0, "alt+tab -> alt flag");

    /* F10 is a syskey without the alt flag */
    {
        KBDLLHOOKSTRUCT k = make_ll(VK_F10, 0x44, 0);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK(ev.event_type == TRK_SYS_KEY_DOWN, "F10 -> TRK_SYS_KEY_DOWN");

    /* Extended right ctrl down: own modifier bit forced on */
    {
        KBDLLHOOKSTRUCT k = make_ll(VK_RCONTROL, 0x1D, LLKHF_EXTENDED);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK((ev.modifier_state & TRK_MOD_RCTRL) != 0, "rctrl down -> RCTRL bit");
    CHECK((ev.flags & TRK_FLAG_EXTENDED) != 0, "rctrl down -> extended flag");

    /* Right ctrl up: bit cleared */
    {
        KBDLLHOOKSTRUCT k = make_ll(VK_RCONTROL, 0x1D, LLKHF_UP | LLKHF_EXTENDED);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK((ev.modifier_state & TRK_MOD_RCTRL) == 0, "rctrl up -> RCTRL bit off");

    /* Caps Lock key down: held bit set, toggle bit reflects the lamp */
    {
        KBDLLHOOKSTRUCT k = make_ll(VK_CAPITAL, 0x3A, 0);
        trk_keyboard_describe(&k, &ev);
    }
    CHECK((ev.modifier_state & TRK_MOD_CAPS) != 0, "caps down -> CAPS held bit");
    /* toggle bit can be either way depending on lamp; just check it exists */
    CHECK(((ev.modifier_state & TRK_MOD_CAPS_ON) != 0) ==
          ((GetKeyState(VK_CAPITAL) & 1) != 0), "caps toggle matches lamp");

    /* NULL out pointer is a no-op (must not crash) */
    {
        KBDLLHOOKSTRUCT k = make_ll('C', 0x2E, 0);
        trk_keyboard_describe(&k, NULL);
    }
    CHECK(1, "describe(NULL out) does not crash");
}

/* ---- part 2: live hook + injected F24 ----------------------------------- */

static volatile LONG g_events_seen = 0;
static volatile LONG g_injected_seen = 0;
static volatile LONG g_f24_seen = 0;   /* injected F24 only: immune to real typing */

static int __stdcall counting_sink(const TrkKeyboardEvent *ev, void *ctx)
{
    (void)ctx;
    InterlockedIncrement(&g_events_seen);
    if (ev->flags & TRK_FLAG_INJECTED) {
        InterlockedIncrement(&g_injected_seen);
    }
    if (ev->vk == VK_F24 && (ev->flags & TRK_FLAG_INJECTED)) {
        InterlockedIncrement(&g_f24_seen);
    }
    return 0;
}

static void tap_f24(void)
{
    INPUT in[2];
    memset(in, 0, sizeof(in));
    in[0].type = INPUT_KEYBOARD;
    in[0].ki.wVk = VK_F24;
    in[1].type = INPUT_KEYBOARD;
    in[1].ki.wVk = VK_F24;
    in[1].ki.dwFlags = KEYEVENTF_KEYUP;
    if (SendInput(2, in, sizeof(INPUT)) != 2) {
        printf("  (SendInput failed: %lu)\n", (unsigned long)GetLastError());
    }
}

static void test_live_hook(void)
{
    int rc;

    printf("part 2: live hook + injected F24 tap\n");

    rc = trk_keyboard_start(counting_sink, NULL);
    CHECK(rc == TRK_OK, "trk_keyboard_start returns TRK_OK");
    CHECK(trk_keyboard_is_running(), "hook reports running");

    /* double start must be refused, first hook stays alive */
    rc = trk_keyboard_start(counting_sink, NULL);
    CHECK(rc == TRK_ERR_ALREADY_RUNNING, "second start refused (ALREADY_RUNNING)");
    CHECK(trk_keyboard_is_running(), "first hook still running after refusal");

    tap_f24();
    Sleep(500);   /* give the hook thread time to deliver */

    /* Counts are keyed to the injected F24 tap so real typing on the live
     * desktop (which the hook correctly also sees) cannot flake asserts. */
    CHECK(g_f24_seen >= 2, "F24 down+up delivered to sink");
    CHECK(g_injected_seen >= 2, "injected events carry the injected flag");
    CHECK(g_events_seen >= g_f24_seen, "total events include any real keys seen");
    printf("  (events seen: %ld, injected: %ld, injected F24: %ld)\n",
           (long)g_events_seen, (long)g_injected_seen, (long)g_f24_seen);

    trk_keyboard_stop();
    CHECK(!trk_keyboard_is_running(), "hook reports stopped");

    /* after stop, no more delivery */
    {
        LONG before = g_f24_seen;
        tap_f24();
        Sleep(300);
        CHECK(g_f24_seen == before, "no delivery after stop");
    }

    /* stopping again is safe */
    trk_keyboard_stop();
    CHECK(1, "double stop does not crash");

    /* restart works (fresh hook) */
    g_events_seen = 0;
    g_injected_seen = 0;
    g_f24_seen = 0;
    rc = trk_keyboard_start(counting_sink, NULL);
    CHECK(rc == TRK_OK, "restart works");
    tap_f24();
    Sleep(400);
    CHECK(g_f24_seen >= 2, "events delivered after restart");
    trk_keyboard_stop();
}

int main(void)
{
    printf("TechReader native keyboard self-test\n");
    printf("compiler: " __DATE__ " " __TIME__ "\n\n");

    test_describe();
    printf("\n");
    test_live_hook();

    printf("\n%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
