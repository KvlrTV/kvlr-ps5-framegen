// KVLR edition: the Settings page in the approved KVLR layout (kvlr/design/settings-layout-mockup.png): tabs across
// the top (Quality, Frame Gen, Colour, Stream, Display) showing only that tab's cards, a "processing order" strip of
// what runs on each frame (dimmed and struck through when off), and an on/off switch on the cards that are one
// effect (Frame generation, Look, OBS output). Built over upstream's page: its cards, rows and live changes are
// reused as they are. Hooks (marked KVLR) in SettingsPage.cs: BuildSettings and RefreshSettings.

using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;

namespace SmoovPlay
{
    partial class Ui
    {
        static readonly string[] KvlrTabs = { "Quality", "Frame Gen", "Colour", "Stream", "Display" };
        static readonly Dictionary<string, string> KvlrTabOf = new Dictionary<string, string>
        {
            { "Picture", "Quality" }, { "Capture card", "Quality" },
            { "Smoothness", "Frame Gen" },
            { "Looks", "Colour" },
            { "PS5 Remote Play", "Stream" }, { "PS5 connection", "Stream" }, { "Instant replay", "Stream" }, { "Sound", "Stream" },
            { "Display", "Display" }, { "OBS output", "Display" },
        };
        static readonly Dictionary<string, string> KvlrMaster = new Dictionary<string, string>
        {
            { "Smoothness", "interp" }, { "Looks", "look_on" }, { "OBS output", "obs_output" },
        };

        string kvlrTab;
        FrameworkElement kvlrTop;
        WrapPanel kvlrStrip;
        readonly Dictionary<string, Border> kvlrTabButtons = new Dictionary<string, Border>();
        readonly Dictionary<string, CheckBox> kvlrSwitches = new Dictionary<string, CheckBox>();

        class KvlrChip
        {
            public readonly string text; public readonly bool on, key;
            public KvlrChip(string t, bool o, bool k) { text = t; on = o; key = k; }
        }

        void KvlrSettingsLayout()
        {
            var stack = E<ScrollViewer>("SetScroll").Content as StackPanel;
            if (stack == null) return;
            if (kvlrTop != null) stack.Children.Remove(kvlrTop);
            kvlrTab = kvlrTab ?? (prefs.FirstOrDefault(p => p.StartsWith("kvlr-tab:")) ?? "kvlr-tab:Quality").Substring(9);
            if (!KvlrTabs.Contains(kvlrTab)) kvlrTab = "Quality";

            var top = new StackPanel { Margin = new Thickness(0, 0, 0, 16) };
            var tabs = new Grid { Margin = new Thickness(0, 0, 0, 12) };
            var bar = new StackPanel { Orientation = Orientation.Horizontal };
            kvlrTabButtons.Clear();
            foreach (var name in KvlrTabs)
            {
                var label = new TextBlock { Text = name, FontSize = 14, FontWeight = FontWeights.SemiBold, Margin = new Thickness(14, 8, 14, 9) };
                var tab = new Border { BorderThickness = new Thickness(0, 0, 0, 2), Child = label, Background = Brushes.Transparent };
                string n = name;
                var press = new Button { Style = S("Bare"), Content = tab, Cursor = System.Windows.Input.Cursors.Hand, Padding = new Thickness(0) };
                press.Click += (o, e) => { kvlrTab = n; KvlrRememberTab(); RefreshSettings(); };
                AutomationProperties.SetAutomationId(press, "kvlr-tab-" + name.Replace(" ", ""));
                AutomationProperties.SetName(press, name + " tab");
                kvlrTabButtons[name] = tab;
                bar.Children.Add(press);
            }
            tabs.Children.Add(new Border { Height = 1, Background = R("Line"), VerticalAlignment = VerticalAlignment.Bottom });
            tabs.Children.Add(bar);
            top.Children.Add(tabs);

            var strip = new Border { Style = S("Card"), Padding = new Thickness(16, 12, 16, 12) };
            var sp = new StackPanel();
            var head = new Grid();
            head.Children.Add(new TextBlock { Text = "PROCESSING ORDER", FontSize = 11, FontWeight = FontWeights.SemiBold, Foreground = R("Muted") });
            head.Children.Add(new TextBlock { Text = "Left to right, every frame", FontSize = 11, Foreground = R("Muted"), HorizontalAlignment = HorizontalAlignment.Right });
            sp.Children.Add(head);
            kvlrStrip = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            sp.Children.Add(kvlrStrip);
            strip.Child = sp;
            top.Children.Add(strip);
            kvlrTop = top;
            stack.Children.Insert(0, top);

            kvlrSwitches.Clear();
            foreach (var sec in settingSections)
            {
                string key;
                if (!KvlrMaster.TryGetValue(sec.Group, out key)) continue;
                var btn = FindFold(sec.Card);
                var g = btn != null ? btn.Content as Grid : null;
                if (g == null) continue;
                g.ColumnDefinitions.Insert(2, new ColumnDefinition { Width = GridLength.Auto });
                foreach (UIElement c in g.Children) if (Grid.GetColumn(c) == 2) Grid.SetColumn(c, 3);
                var sw = new CheckBox { Style = S("Switch"), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(10, 0, 0, 0) };
                AutomationProperties.SetAutomationId(sw, "kvlr-switch-" + key);
                string k = key;
                sw.Checked += (o, e) => KvlrSwitch(k, true);
                sw.Unchecked += (o, e) => KvlrSwitch(k, false);
                Grid.SetColumn(sw, 2);
                g.Children.Add(sw);
                kvlrSwitches[key] = sw;
            }
            KvlrRefresh();
        }

        static Button FindFold(DependencyObject root)
        {
            foreach (var child in LogicalTreeHelper.GetChildren(root).OfType<DependencyObject>())
            {
                var b = child as Button;
                if (b != null && b.Content is Grid) return b;
                var deeper = FindFold(child);
                if (deeper != null) return deeper;
            }
            return null;
        }

        void KvlrRememberTab()
        {
            prefs.RemoveWhere(p => p.StartsWith("kvlr-tab:"));
            prefs.Add("kvlr-tab:" + kvlrTab);
            Prefs.Save(prefs);
        }

        void KvlrApplyTab()
        {
            foreach (var kv in kvlrTabButtons)
            {
                bool on = kv.Key == kvlrTab;
                kv.Value.BorderBrush = on ? R("Accent") : Brushes.Transparent;
                ((TextBlock)kv.Value.Child).Foreground = on ? R("Accent") : R("Text2");
            }
            // RefreshSettings has shown each card that has rows to show; cards on other tabs are hidden here
            foreach (var sec in settingSections)
            {
                string tab;
                if (!(KvlrTabOf.TryGetValue(sec.Group, out tab) ? tab == kvlrTab : kvlrTab == "Display")) Show(sec.Card, false);
            }
            if (kvlrTab != "Frame Gen") Show(E("SetQuick"), false); else Show(E("SetQuick"), true);
            Show(E("DetectCard"), kvlrTab == "Quality");
        }

        void KvlrSwitch(string key, bool on)
        {
            if (syncingSettings) return;
            var spec = settingSpecs != null ? settingSpecs.FirstOrDefault(s => s.Key == key) : null;
            if (spec != null) ChangeSetting(spec, on);
        }

        /// <summary>The strip and the card switches, from the current values (the session's while playing).</summary>
        void KvlrRefresh()
        {
            if (!kvlrSoundShown && settingSpecs != null) BuildChips();  // the Play page's Sound out, once the list is in
            if (kvlrStrip == null) return;
            KvlrApplyTab();
            bool was = syncingSettings;
            syncingSettings = true;
            try
            {
                foreach (var kv in kvlrSwitches) kv.Value.IsChecked = SettingText(kv.Key) == "true";
            }
            finally { syncingSettings = was; }

            string scaler = SettingText("scaler") ?? "fsr", hz = SettingText("hz") ?? "60";
            bool interp = SettingText("interp") != "false";
            string up = scaler == "dlss" ? "DLSS SR" : scaler == "vsr" ? "RTX VSR"
                      : scaler == "bilinear" ? "Bilinear" : "FSR 1";
            string model = SettingText("model");
            string fg = (model == "dlssg" ? "NVIDIA DLSS FG" : model == "vfg" ? "NVIDIA VFG" : "RIFE")
                        + " · " + hz + " fps";
            string input = source == null ? "Input" : source.Kind == "capture" ? "Capture card"
                         : source.RemotePlay ? "PS5 Remote Play" : "Input";
            var chips = new List<KvlrChip>
            {
                new KvlrChip(input, true, false),
                new KvlrChip("Upscale · " + up, true, true),
                new KvlrChip("Frame generation · " + fg, interp, true),
                new KvlrChip("Steady HUD", interp && SettingText("steady_hud") == "true", false),
                new KvlrChip("Look", SettingText("look_on") == "true", false),
                new KvlrChip(SettingText("fullscreen") == "false" ? "Window" : "Fullscreen", true, false),
                new KvlrChip("OBS output", SettingText("obs_output") == "true", false),
            };
            kvlrStrip.Children.Clear();
            for (int i = 0; i < chips.Count; i++)
            {
                var c = chips[i];
                if (i > 0) kvlrStrip.Children.Add(new TextBlock { Text = "→", Foreground = R("Muted"), FontSize = 12, Margin = new Thickness(6, 4, 6, 0) });
                var t = new TextBlock { Text = c.text, FontSize = 12, FontWeight = FontWeights.SemiBold, Foreground = !c.on ? R("Muted") : c.key ? R("Accent") : R("Text") };
                if (!c.on) t.TextDecorations = TextDecorations.Strikethrough;
                kvlrStrip.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(7), BorderThickness = new Thickness(1), Padding = new Thickness(9, 3, 9, 4), Margin = new Thickness(0, 2, 0, 2),
                    BorderBrush = c.on && c.key ? R("Accent") : R("Line2"), Background = Solid("#11171A"), Child = t, Opacity = c.on ? 1.0 : 0.7,
                });
            }
        }
    }
}
