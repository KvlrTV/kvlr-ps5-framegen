// KVLR edition: one-click PS5 connect. The "PS5 connection" settings (framegen/kvlr_settings.py) are written into
// chiaki-ng's own saved settings (Qt QSettings, HKCU\Software\Chiaki\Chiaki) just before Play starts chiaki-ng:
//   ps5_console  a registered console's nickname: chiaki-ng's Auto-Connect points at it, so chiaki-ng finds it,
//                wakes it from rest mode and goes straight into the stream; "ask" clears it (the console list).
//   ps5_codec    auto: H.265, or H.265 HDR when the pipeline's HDR output is on; h264; keep: untouched.
//   ps5_bitrate  "100" / "50" / "30" Mbps for the home network; keep: untouched.
// Open chiaki-ng on the guide page clears Auto-Connect first, so registering another console still shows the list.
// Only a chiaki-ng this launcher is about to start is changed: Start isn't called while one is running.
// Hooks (marked KVLR): Core.cs before Chiaki.Start in the Play flow, Ui.cs OpenChiaki.

using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace SmoovPlay
{
    static class KvlrChiaki
    {
        const string Root = @"Software\Chiaki\Chiaki";

        static Dictionary<string, object> Settings()
        {
            try
            {
                var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Paths.SettingsFile));
                return d ?? new Dictionary<string, object>();
            }
            catch (Exception) { return new Dictionary<string, object>(); }
        }

        static string Get(Dictionary<string, object> s, string key, string fallback)
        {
            object v;
            return s.TryGetValue(key, out v) && v != null ? Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture) : fallback;
        }

        /// <summary>The registered console's server_mac value (Qt's "@ByteArray(...)" text) for a nickname, or null.</summary>
        static string ConsoleMac(RegistryKey root, string nickname)
        {
            using (var hosts = root.OpenSubKey("registered_hosts"))
            {
                if (hosts == null) return null;
                foreach (var name in hosts.GetSubKeyNames())
                    using (var h = hosts.OpenSubKey(name))
                    {
                        if (h == null) continue;
                        if (string.Equals(h.GetValue("server_nickname") as string, nickname, StringComparison.Ordinal))
                            return h.GetValue("server_mac") as string;
                    }
            }
            return null;
        }

        /// <summary>The "ps5_console" setting: a registered console's nickname, or "ask".</summary>
        public static string Console() { return Get(Settings(), "ps5_console", "ask"); }

        /// <summary>Before Play starts chiaki-ng: the console to auto-connect to, the codec and the bitrate.</summary>
        public static void BeforePlay(Action<string> log)
        {
            try
            {
                var s = Settings();
                using (var root = Registry.CurrentUser.OpenSubKey(Root, true))
                {
                    if (root == null) { log("[kvlr] chiaki-ng has no saved settings yet: connect your PS5 first"); return; }
                    using (var st = root.CreateSubKey("settings"))
                    {
                        string console = Get(s, "ps5_console", "ask");
                        string mac = console == "ask" ? null : ConsoleMac(root, console);
                        if (console != "ask" && mac == null)
                            log("[kvlr] " + console + " isn't registered in chiaki-ng any more: showing the console list");
                        if (mac != null) st.SetValue("auto_connect_mac", mac);
                        else st.DeleteValue("auto_connect_mac", false);
                        if (mac != null) log("[kvlr] connecting to " + console + " by itself (it's woken if it's resting)");

                        // What closing chiaki-ng's window does to the session (never "ask": a dialog mid-stop)
                        st.SetValue("disconnect_action", Get(s, "ps5_on_stop", "end") == "rest" ? "sleep" : "nothing");

                        string codec = Get(s, "ps5_codec", "auto");
                        if (codec != "keep")
                        {
                            string v = codec == "h264" ? "h264" : Get(s, "hdr", "off") == "hdr10" ? "h265_hdr" : "h265";
                            st.SetValue("codec_local_ps5", v);
                            log("[kvlr] stream codec " + v);
                        }

                        string rate = Get(s, "ps5_bitrate", "keep");
                        int mbps;
                        if (rate != "keep" && int.TryParse(rate, out mbps) && mbps > 0)
                        {
                            st.SetValue("bitrate_local_ps5", (mbps * 1000).ToString());
                            log("[kvlr] stream bitrate " + mbps + " Mbps");
                        }
                    }
                }
            }
            catch (Exception e) { log("[kvlr] couldn't set chiaki-ng up for one-click connect: " + e.Message); }
        }

        /// <summary>The "ps5_on_stop" setting: end, rest or keep.</summary>
        public static string OnStop() { return Get(Settings(), "ps5_on_stop", "end"); }

        /// <summary>After a Remote Play session stops: closes the chiaki-ng Play started, which ends the PS5's stream
        /// (chiaki-ng's own close: rest asks the PS5 to go into rest mode first). Runs off the UI thread.</summary>
        public static void EndRemotePlay(Paths p, bool rest, Action<string> log)
        {
            var pr = Chiaki.Ours(p);
            if (pr == null) return;
            try
            {
                using (var st = Registry.CurrentUser.CreateSubKey(Root + @"\settings"))
                    st.SetValue("disconnect_action", rest ? "sleep" : "nothing");
            }
            catch (Exception) { }
            log(rest ? "[kvlr] ending Remote Play and putting the PS5 into rest mode" : "[kvlr] ending Remote Play");
            try
            {
                // chiaki-ng's first close ends the session (rest mode first, if asked); the window may then stay on its
                // console list, so close again, and only force it after that.
                for (int i = 0; i < 2 && !pr.HasExited; i++)
                {
                    pr.Refresh();
                    pr.CloseMainWindow();
                    if (pr.WaitForExit(rest ? 4000 : 2500)) break;
                }
                if (!pr.HasExited) pr.Kill();
            }
            catch (Exception e) { log("[kvlr] couldn't close chiaki-ng: " + e.Message); }
        }

        /// <summary>Before the guide's Open chiaki-ng: no Auto-Connect, so the console list (and Register) shows.</summary>
        public static void ForSetup()
        {
            try
            {
                using (var st = Registry.CurrentUser.OpenSubKey(Root + @"\settings", true))
                    if (st != null) st.DeleteValue("auto_connect_mac", false);
            }
            catch (Exception) { }
        }
    }
}
