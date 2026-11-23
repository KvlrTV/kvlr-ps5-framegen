// KVLR: which build this is. Both builds update from the same GitHub releases; each release carries one setup per
// build, and a copy only takes its own (GitHub.SetupName), so the private build never becomes the public one and the
// public one never picks up the private extras. kvlr/build_kvlr.py --private rewrites Name in its branded copy.
namespace SmoovPlay
{
    static class KvlrChannel
    {
        public const string Name = "public";

        public static bool Private { get { return Name == "private"; } }

        /// <summary>The release asset this build installs: the public setup keeps upstream's name, so
        /// gta.kvlrtv.com's link and every installed public copy carry on unchanged.</summary>
        public static string SetupName { get { return Private ? "KVLR-Private-Setup.exe" : "SmoovPlay-Setup.exe"; } }
    }
}
