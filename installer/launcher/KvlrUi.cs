// KVLR edition: the PS5 that one-click connect uses (settings "ps5_console", KvlrChiaki.cs), shown on the Play page
// as a chip with its state, found the way chiaki-ng finds consoles: a PlayStation discovery packet (UDP 9302,
// broadcast) answered by "200 Ok" (on) or "620 Server Standby" (rest mode). Probed when the Play page shows and every
// few seconds while it's up and nothing is playing. Hooks (marked KVLR): Ui.cs BuildChips and the Play page's idle
// subtitle.

using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.Windows.Shapes;

namespace SmoovPlay
{
    partial class Ui
    {
        TextBlock kvlrPs5Text;
        Ellipse kvlrPs5Dot;
        DispatcherTimer kvlrPs5Timer;
        int kvlrProbing;

        /// <summary>The console Play connects to by itself, or null when it asks (or the source isn't Remote Play).</summary>
        string KvlrConsole()
        {
            if (!source.RemotePlay) return null;
            string c = KvlrChiaki.Console();
            return c == null || c == "ask" ? null : c;
        }

        /// <summary>The Play page's idle line when one-click connect is on, else null (upstream's line).</summary>
        string KvlrPlaySub()
        {
            string c = KvlrConsole();
            return c == null ? null
                : "Press Play. It connects to " + c + " by itself, waking it if it's resting, and the smooth video "
                  + "appears in its own window.";
        }

        bool kvlrRestOnce;  // Rest PS5 was pressed: this stop rests the PS5 whatever "ps5_on_stop" says

        bool KvlrPlaying { get { return session != null && session.Running; } }

        /// <summary>Play state changes: after a Remote Play session stops or ends, end the PS5's stream too (closing
        /// chiaki-ng), unless the setting keeps it; the chips follow (Rest PS5 shows only while playing).</summary>
        void KvlrOnState(PlayState st)
        {
            if (st == PlayState.Playing || st == PlayState.Stopped || st == PlayState.Ended || st == PlayState.Error)
                BuildChips();
            if (!source.RemotePlay || (st != PlayState.Stopped && st != PlayState.Ended)) return;
            bool rest = kvlrRestOnce || KvlrChiaki.OnStop() == "rest";
            kvlrRestOnce = false;
            if (!rest && KvlrChiaki.OnStop() == "keep") return;
            var p = paths;
            System.Threading.Tasks.Task.Run(() => KvlrChiaki.EndRemotePlay(p, rest, l => playLog.Add(l)));
            if (rest) Toast("Putting the PS5 into rest mode...", false);
        }

        void KvlrPs5Chip(WrapPanel chips)
        {
            kvlrPs5Text = null;
            string c = KvlrConsole();
            if (c == null) return;
            if (KvlrPlaying)
            {
                var rest = new Button { Style = S("Ghost"), Content = "Rest PS5", Margin = new Thickness(4), Padding = new Thickness(14, 6, 14, 6) };
                rest.ToolTip = "Stops playing, ends Remote Play and puts " + c + " into rest mode.";
                rest.Click += (s, e) => { kvlrRestOnce = true; if (KvlrPlaying) session.Stop(); };
                System.Windows.Automation.AutomationProperties.SetAutomationId(rest, "KvlrRestPs5");
                chips.Children.Add(rest);
            }
            var b = new Border { CornerRadius = new CornerRadius(15), Background = Solid("#171B22"), BorderBrush = R("Line2"), BorderThickness = new Thickness(1), Padding = new Thickness(12, 6, 14, 6), Margin = new Thickness(4) };
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            sp.Children.Add(new TextBlock { Style = S("Icon"), Text = "", FontSize = 12, Foreground = R("Accent") });
            kvlrPs5Text = new TextBlock { Text = c, FontSize = 12.5, Margin = new Thickness(8, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
            sp.Children.Add(kvlrPs5Text);
            kvlrPs5Dot = new Ellipse { Width = 7, Height = 7, Margin = new Thickness(9, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, Fill = R("Muted") };
            sp.Children.Add(kvlrPs5Dot);
            b.Child = sp;
            b.ToolTip = "The PS5 Play connects to. Change it on the Settings page, under PS5 connection.";
            chips.Children.Add(b);
            KvlrProbe(c);
            if (kvlrPs5Timer == null)
            {
                kvlrPs5Timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(6) };
                kvlrPs5Timer.Tick += (s, e) =>
                {
                    string now = KvlrConsole();
                    if (kvlrPs5Text != null && now != null && page == "PagePlay" && Window.IsVisible
                        && Window.WindowState != WindowState.Minimized)
                        KvlrProbe(now);
                };
                kvlrPs5Timer.Start();
            }
        }

        void KvlrProbe(string console)
        {
            if (Interlocked.Exchange(ref kvlrProbing, 1) == 1) return;
            var th = new Thread(() =>
            {
                string state = "missing", ip = null;
                try { KvlrDiscover(console, out state, out ip); }
                catch (Exception) { }
                finally { Interlocked.Exchange(ref kvlrProbing, 0); }
                OnUi(() =>
                {
                    if (kvlrPs5Text == null) return;
                    string text, dot, tip;
                    if (state == "on") { text = console + "  ·  Ready"; dot = "Good"; tip = "On, at " + ip + ". Play connects straight away."; }
                    else if (state == "standby") { text = console + "  ·  Resting"; dot = "Warn"; tip = "In rest mode, at " + ip + ". Play wakes it first (a few seconds)."; }
                    else { text = console + "  ·  Not found"; dot = "Muted"; tip = "No answer on your network: it may be off (not in rest mode), or on another network. Play still tries."; }
                    kvlrPs5Text.Text = text;
                    kvlrPs5Dot.Fill = R(dot);
                    ((FrameworkElement)kvlrPs5Text.Parent).ToolTip = tip + " Change the console on the Settings page, under PS5 connection.";
                });
            }) { IsBackground = true, Name = "kvlr-ps5-probe" };
            th.Start();
        }

        /// <summary>Asks the network for PlayStations and reports the named one's state: on, standby or missing.</summary>
        static void KvlrDiscover(string console, out string state, out string ip)
        {
            state = "missing"; ip = null;
            var msg = Encoding.ASCII.GetBytes("SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n");
            using (var u = new UdpClient(0))
            {
                u.EnableBroadcast = true;
                u.Client.ReceiveTimeout = 400;
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    u.Send(msg, msg.Length, new IPEndPoint(IPAddress.Broadcast, 9302));
                    var until = DateTime.UtcNow.AddMilliseconds(900);
                    while (DateTime.UtcNow < until)
                    {
                        IPEndPoint from = null;
                        byte[] data;
                        try { data = u.Receive(ref from); }
                        catch (SocketException) { break; }
                        string reply = Encoding.ASCII.GetString(data);
                        string name = null;
                        foreach (var line in reply.Split('\n'))
                            if (line.StartsWith("host-name:", StringComparison.OrdinalIgnoreCase)) name = line.Substring(10).Trim();
                        if (!string.Equals(name, console, StringComparison.Ordinal)) continue;
                        ip = from.Address.ToString();
                        state = reply.StartsWith("HTTP/1.1 200") ? "on" : reply.StartsWith("HTTP/1.1 620") ? "standby" : "missing";
                        return;
                    }
                }
            }
        }
    }
}
