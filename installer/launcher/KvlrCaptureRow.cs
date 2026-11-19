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
            string now = SettingText("audio_out") ?? Json.Serialize(spec.Default).Trim('"');
            var drop = KvlrDrop("kvlr-audio-out", "Sound out",
                                spec.Choices.Select(c => Kv((string)c.Key, c.Value)), now,
                                v => KvlrSet("audio_out", v, nextPlay: true), minWidth: 230);
            drop.MaxWidth = 340;
            var lab = Labelled("Sound out", drop);
            ((FrameworkElement)lab).Margin = new Thickness(4, 4, 4, 4);
            chips.Children.Add(lab);
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
