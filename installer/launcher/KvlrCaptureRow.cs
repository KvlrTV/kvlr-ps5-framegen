// KVLR edition: the capture card's picture and output choices on the Play page, under the Card / Sound row, so they can
// be switched without going to Settings: Capture (settings "capture_size"), AI frames at ("capture_work") and Output
// (30 = frame generation off, or 60 / 90 / 120 fps: "interp" and "hz"). Output changes apply at once while playing,
// through the same path as the Settings page (ChangeSetting); the two size choices take effect from the next Play.
// Hook (marked KVLR): Ui.cs BuildDevices, after Look again.

using System;
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
        void KvlrCaptureOptions(WrapPanel host)
        {
            var row = new WrapPanel { Margin = new Thickness(0, 4, 0, 0) };
            row.Children.Add(Labelled("Capture", KvlrDrop("kvlr-capture-size", "Capture size", new[]
            {
                Kv("1080p", "1080p · 60 fps"), Kv("1440p", "1440p · 30 fps on some cards"), Kv("2160p", "4K"),
            }, SettingText("capture_size") ?? "1080p", v => KvlrSet("capture_size", v, nextPlay: true))));
            row.Children.Add(Labelled("AI frames at", KvlrDrop("kvlr-capture-work", "Frame generation size", new[]
            {
                Kv("auto", "Auto"), Kv("native", "As captured"), Kv("1440", "1440p"), Kv("1080", "1080p"),
            }, SettingText("capture_work") ?? "auto", v => KvlrSet("capture_work", v, nextPlay: true))));
            string output = SettingText("interp") == "false" ? "30" : SettingText("hz") ?? "60";
            row.Children.Add(Labelled("Output", KvlrDrop("kvlr-output-rate", "Output frame rate", new[]
            {
                Kv("30", "30 fps · as the game sends it"), Kv("60", "60 fps"), Kv("90", "90 fps"), Kv("120", "120 fps"),
            }, output, v =>
            {
                if (v == "30") { KvlrSet("interp", false); return; }
                KvlrSet("interp", true);
                KvlrSet("hz", int.Parse(v));
            }, minWidth: 150)));
            var note = new TextBlock { Text = "Output switches live; Capture and AI frames apply from the next Play.",
                                       FontSize = 11.5, Foreground = R("Text2"), Margin = new Thickness(6, 6, 6, 0),
                                       VerticalAlignment = VerticalAlignment.Center };
            row.Children.Add(note);
            host.Children.Add(row);
        }

        static KeyValuePair<string, string> Kv(string k, string v) { return new KeyValuePair<string, string>(k, v); }

        /// <summary>Sound out ("audio_out") under the Play page's chips, for every source: the capture card's sound
        /// and chiaki-ng's (Remote Play). Applies from the next Play.</summary>
        bool kvlrSoundShown;

        void KvlrSoundOut(WrapPanel chips)
        {
            var spec = settingSpecs != null ? settingSpecs.FirstOrDefault(s => s.Key == "audio_out") : null;
            kvlrSoundShown = spec != null;
            if (spec == null) { LoadSettingSpecs(); return; }  // drawn once the list arrives (KvlrRefresh)
            string now = KvlrSettingFull("audio_out") ?? Json.Serialize(spec.Default).Trim('"');
            var drop = KvlrDrop("kvlr-audio-out", "Sound out",
                                spec.Choices.Select(c => Kv((string)c.Key, c.Value)), now,
                                v => KvlrSet("audio_out", v, nextPlay: true), minWidth: 230);
            drop.MaxWidth = 340;
            var lab = Labelled("Sound out", drop);
            ((FrameworkElement)lab).Margin = new Thickness(4, 4, 4, 4);
            chips.Children.Add(lab);
            KvlrPolish(chips);
        }

        /// <summary>The Polish sliders ("polish_sharpen" ... "polish_grain", 0-100 %, framegen/kvlr_looks.py): one per
        /// effect, each changing the picture at once while playing, and Save as look, which keeps what's on now
        /// (look + Polish) as one of the user's own looks. Double-click a slider for 0.</summary>
        void KvlrPolish(WrapPanel chips)
        {
            var row = new WrapPanel { Margin = new Thickness(4, 4, 4, 4), VerticalAlignment = VerticalAlignment.Center };
            row.Children.Add(new TextBlock { Text = "Polish", FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = R("Text2"),
                                             Margin = new Thickness(0, 0, 10, 0), VerticalAlignment = VerticalAlignment.Center });
            var parts = new[]
            {
                new[] { "polish_sharpen", "Sharpen", "Sharper across edges and detail, no halos." },
                new[] { "polish_edges", "Smooth edges", "Fills in stair-steps along edges without blurring across them." },
                new[] { "polish_noise", "Smooth noise", "Smooths speckle in flat areas; keeps edges and texture." },
                new[] { "polish_clarity", "Clarity", "Local contrast: texture and depth read stronger." },
                new[] { "polish_grain", "Grain", "Fine film grain. Off by default." },
            };
            foreach (var part in parts) row.Children.Add(KvlrPolishSlider(part[0], part[1], part[2]));
            var save = new Button { Style = S("Ghost"), Content = "Save as look", Margin = new Thickness(4, 0, 0, 0), Padding = new Thickness(12, 4, 12, 4) };
            AutomationProperties.SetAutomationId(save, "kvlr-polish-save");
            save.ToolTip = "Saves what you see now (your look, if one is on, plus Polish) as your own look, to pick again later on the Looks page or with J.";
            save.Click += (o, e) =>
            {
                save.IsEnabled = false;
                System.Threading.Tasks.Task.Run(() =>
                {
                    var lines = new List<string>();
                    try { Proc.Run(Proc.Python(paths.Python, "-m framegen.kvlr_looks save-polish", paths.App), l => { lock (lines) lines.Add(l); }, null); }
                    catch (Exception ex) { lock (lines) lines.Add("{\"error\": \"" + ex.Message.Replace("\"", "'") + "\"}"); }
                    string json;
                    lock (lines) json = lines.LastOrDefault(l => l.StartsWith("{")) ?? "{\"error\": \"no answer\"}";
                    Window.Dispatcher.Invoke(() =>
                    {
                        save.IsEnabled = true;
                        Dictionary<string, object> r = null;
                        try { r = Json.DeserializeObject(json) as Dictionary<string, object>; } catch (Exception) { }
                        if (r != null && r.ContainsKey("name")) Toast("Saved as \"" + r["name"] + "\" on the Looks page", false);
                        else Toast(r != null && r.ContainsKey("error") ? Convert.ToString(r["error"]) : "Couldn't save the look", true);
                    });
                });
            };
            row.Children.Add(save);
            chips.Children.Add(row);
        }

        FrameworkElement KvlrPolishSlider(string key, string label, string tip)
        {
            int now;
            if (!int.TryParse(KvlrSettingFull(key) ?? "0", out now)) now = 0;
            var box = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 12, 0), VerticalAlignment = VerticalAlignment.Center };
            box.Children.Add(new TextBlock { Text = label, FontSize = 12, Foreground = R("Text2"), Margin = new Thickness(0, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center });
            var slider = new Slider
            {
                Style = S("Slide"), Minimum = 0, Maximum = 100, Value = now, SmallChange = 5, LargeChange = 20, Width = 110,
                TickFrequency = 5, IsSnapToTickEnabled = true, IsMoveToPointEnabled = true, VerticalAlignment = VerticalAlignment.Center,
                ToolTip = tip + " Changes at once. Double-click for 0.",
            };
            AutomationProperties.SetAutomationId(slider, "kvlr-" + key.Replace('_', '-'));
            AutomationProperties.SetName(slider, label);
            var text = new TextBlock { Text = now + "%", Width = 38, FontSize = 12, Foreground = R("Text"), Margin = new Thickness(6, 0, 0, 0),
                                       FontFamily = (FontFamily)Window.FindResource("Mono"), VerticalAlignment = VerticalAlignment.Center };
            int last = now;
            slider.ValueChanged += (o, e) =>
            {
                int v = (int)(Math.Round(slider.Value / 5.0) * 5);
                text.Text = v + "%";
                if (v == last) return;
                last = v;
                KvlrSet(key, v);
            };
            slider.MouseDoubleClick += (o, e) => { slider.Value = 0; };
            box.Children.Add(slider);
            box.Children.Add(text);
            return box;
        }

        /// <summary>A setting's whole text value: SettingText's file fallback (Prefs.Setting) stops at the first space,
        /// which cuts "Game (2- BEACN Mix Create)" to "Game".</summary>
        string KvlrSettingFull(string key)
        {
            var values = liveState != null ? liveState["values"] as Dictionary<string, object> : null;
            if (values != null && values.ContainsKey(key)) return Json.Serialize(values[key]).Trim('"');
            try
            {
                var d = Json.DeserializeObject(System.IO.File.ReadAllText(Paths.SettingsFile)) as Dictionary<string, object>;
                object v;
                if (d != null && d.TryGetValue(key, out v) && v != null) return Convert.ToString(v);
            }
            catch (Exception) { }
            return null;
        }

        void KvlrSet(string key, object value, bool nextPlay = false)
        {
            var spec = settingSpecs != null ? settingSpecs.FirstOrDefault(s => s.Key == key) : null;
            ChangeSetting(spec ?? new SettingSpec { Key = key }, value);
            if (nextPlay && session != null && session.Running) Toast("Saved: it applies the next time you press Play", false);
        }

        /// <summary>A drop-down like the card's, but usable while playing.</summary>
        ComboBox KvlrDrop(string id, string name, IEnumerable<KeyValuePair<string, string>> choices, string selected,
                          Action<string> picked, double minWidth = 170)
        {
            var drop = new ComboBox { Style = S("Drop"), MinWidth = minWidth, MaxWidth = 260, VerticalAlignment = VerticalAlignment.Center };
            AutomationProperties.SetAutomationId(drop, id);
            AutomationProperties.SetName(drop, name);
            foreach (var c in choices)
            {
                var item = new ComboBoxItem { Style = S("DropItem"), Content = c.Value, Tag = c.Key, ToolTip = c.Value };
                drop.Items.Add(item);
                if (c.Key == selected) drop.SelectedItem = item;
            }
            if (drop.SelectedItem == null && drop.Items.Count > 0) drop.SelectedIndex = 0;
            drop.SelectionChanged += (o, e) => { if (drop.SelectedItem is ComboBoxItem it) picked((string)it.Tag); };
            return drop;
        }
    }
}
