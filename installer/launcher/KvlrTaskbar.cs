// KVLR edition: one taskbar button. The launcher, the video window (the pipeline's Python) and the chiaki-ng it
// started each get the same Windows app ID and the KVLR icon (window properties: System.AppUserModel.ID and its
// relaunch command, name and icon), so Windows groups them under one KVLR PS5 Frame Gen button instead of showing
// a SmoovPlay, a Python and a chiaki-ng icon. A timer looks for new windows every two seconds; each window is set
// once. Hook (marked KVLR): Ui.cs, where the window is set up.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Interop;
using System.Windows.Threading;

namespace SmoovPlay
{
    static class KvlrTaskbar
    {
        public const string AppId = "KvlrTV.KvlrPS5FrameGen";
        const string Name = "KVLR PS5 Frame Gen";
        static readonly HashSet<IntPtr> done = new HashSet<IntPtr>();
        static DispatcherTimer timer;

        public static void Start(System.Windows.Window window, Paths p)
        {
            try { SetCurrentProcessExplicitAppUserModelID(AppId); } catch (Exception) { }
            if (timer != null) return;
            timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            timer.Tick += (s, e) => Tick(window, p);
            timer.Start();
            Tick(window, p);
        }

        static void Tick(System.Windows.Window window, Paths p)
        {
            try
            {
                var pids = new HashSet<int> { Process.GetCurrentProcess().Id };
                var chiaki = Chiaki.Ours(p);
                if (chiaki != null) pids.Add(chiaki.Id);
                string runtime = Path.GetFullPath(p.Runtime).TrimEnd('\\') + "\\";
                foreach (var name in new[] { "python", "pythonw" })
                    foreach (var pr in Process.GetProcessesByName(name))
                        try
                        {
                            string f = pr.MainModule.FileName;
                            if (f.StartsWith(runtime, StringComparison.OrdinalIgnoreCase) || (p.Dev && f.Equals(p.Python, StringComparison.OrdinalIgnoreCase)))
                                pids.Add(pr.Id);
                        }
                        catch (Exception) { }
                string exe = Process.GetCurrentProcess().MainModule.FileName;
                EnumWindows((h, l) =>
                {
                    if (done.Contains(h) || !IsWindowVisible(h)) return true;
                    int pid;
                    GetWindowThreadProcessId(h, out pid);
                    if (pids.Contains(pid) && GetWindow(h, 4 /* GW_OWNER */) == IntPtr.Zero && Tag(h, exe)) done.Add(h);
                    return true;
                }, IntPtr.Zero);
                done.RemoveWhere(h => !IsWindow(h));
            }
            catch (Exception) { }
        }

        // ---- the window's property store
        static readonly Guid Fmt = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");  // PKEY_AppUserModel_*

        static bool Tag(IntPtr hwnd, string exe)
        {
            IPropertyStore ps;
            var iid = typeof(IPropertyStore).GUID;
            if (SHGetPropertyStoreForWindow(hwnd, ref iid, out ps) != 0 || ps == null) return false;
            try
            {
                Set(ps, 2, "\"" + exe + "\"");       // RelaunchCommand
                Set(ps, 4, Name);                    // RelaunchDisplayNameResource
                Set(ps, 3, exe + ",0");              // RelaunchIconResource
                Set(ps, 5, AppId);                   // ID (last, so the group forms with the rest set)
                ps.Commit();
                return true;
            }
            catch (Exception) { return false; }
            finally { Marshal.ReleaseComObject(ps); }
        }

        static void Set(IPropertyStore ps, int pid, string value)
        {
            var key = new PropertyKey { fmtid = Fmt, pid = pid };
            var v = new PropVariant { vt = 31 /* VT_LPWSTR */, p = Marshal.StringToCoTaskMemUni(value) };
            try { ps.SetValue(ref key, ref v); }
            finally { PropVariantClear(ref v); }
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct PropertyKey { public Guid fmtid; public int pid; }

        [StructLayout(LayoutKind.Explicit)]
        struct PropVariant
        {
            [FieldOffset(0)] public ushort vt;
            [FieldOffset(8)] public IntPtr p;
            [FieldOffset(16)] public IntPtr pad;
        }

        [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IPropertyStore
        {
            void GetCount(out uint count);
            void GetAt(uint index, out PropertyKey key);
            void GetValue(ref PropertyKey key, out PropVariant value);
            void SetValue(ref PropertyKey key, ref PropVariant value);
            void Commit();
        }

        delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr hwnd, uint cmd);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out int pid);
        [DllImport("shell32.dll")] static extern int SHGetPropertyStoreForWindow(IntPtr hwnd, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IPropertyStore ps);
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)] static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
        [DllImport("ole32.dll")] static extern int PropVariantClear(ref PropVariant pvar);
    }
}
