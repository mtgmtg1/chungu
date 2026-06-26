// [Flow: Step 1 (로그인 확인) -> Step 2 (중앙 업로드 영역) -> Step 3 (업로드 -> 비용 확인 페이지 이동) -> Step 4 (승인 -> 결과 페이지 이동)]
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileUp, Loader2, LogIn, Coins } from "lucide-react";
import SoftAurora from "../components/SoftAurora.jsx";
import { useAuth } from "../AuthContext.jsx";
import { api } from "../api.js";

export default function UploadPage() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const nav = useNavigate();
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    api
      .me()
      .then(setProfile)
      .catch(() => {});
  }, [user]);

  async function traverseEntry(entry, collected, basePath = "") {
    if (entry.isFile) {
      const file = await new Promise((resolve) => entry.file(resolve));
      file.webkitRelativePath = basePath + file.name;
      collected.push(file);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries = await new Promise((resolve) =>
        reader.readEntries(resolve),
      );
      for (const child of entries) {
        await traverseEntry(child, collected, basePath + entry.name + "/");
      }
    }
  }

  async function handleDrop(e) {
    e.preventDefault();
    const items = Array.from(e.dataTransfer.items || []);
    if (!items.length) return;
    const collected = [];
    for (const item of items) {
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) {
        await traverseEntry(entry, collected);
      } else {
        const file = item.getAsFile ? item.getAsFile() : null;
        if (file) collected.push(file);
      }
    }
    if (collected.length) setFiles(collected);
  }

  async function handleUpload(e) {
    e.preventDefault();
    setError("");
    if (!user) return nav("/login");
    if (!files.length) return setError(t("page:upload.selectFile"));

    const fd = new FormData();
    const relativePaths = [];
    files.forEach((f) => {
      fd.append("files", f);
      relativePaths.push(f.webkitRelativePath || f.name);
    });
    fd.append("relative_paths", JSON.stringify(relativePaths));

    setSubmitting(true);
    try {
      const res = await api.uploadJob(fd);
      nav(`/jobs/${res.job_id}/confirm`);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (authLoading) {
    return (
      <div
        className="min-h-screen bg-background flex items-center justify-center"
        data-oid="06unz7v"
      >
        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid=".kaa-8b"
        />
      </div>
    );
  }

  return (
    <div
      className="min-h-screen bg-background text-on-background flex flex-col overflow-x-hidden"
      data-oid="k:ycgpr"
    >
      <nav className="w-full bg-transparent" data-oid="rn494r3">
        <div
          className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter"
          data-oid="wa08_8a"
        >
          <div className="flex items-center gap-2" data-oid="3q94c.b">
            <span
              className="font-headline-md text-headline-md font-bold text-primary tracking-tight"
              data-oid="m_8vzvl"
            >
              Chungu
            </span>
          </div>
          <div className="flex items-center gap-6" data-oid="87l13er">
            {user ? (
              <>
                <Link
                  to="/dashboard"
                  className="text-body-md text-on-surface-variant hover:text-primary transition-colors font-medium"
                  data-oid="njbsv_m"
                >
                  {t("page:upload.myJobs")}
                </Link>
                <Link
                  to="/payment"
                  className="text-body-md flex items-center gap-1 text-primary hover:underline font-medium"
                  data-oid="u--i569"
                >
                  <Coins size={18} data-oid="ca9h1s8" />{" "}
                  {profile?.points_balance ?? "-"} {t("page:upload.points")}
                </Link>
              </>
            ) : (
              <Link
                to="/login"
                className="text-body-md flex items-center gap-1 text-on-surface-variant hover:text-primary transition-colors font-medium"
                data-oid="31nk.-0"
              >
                <LogIn size={18} data-oid="9.57yvk" /> {t("common:auth.login")}
              </Link>
            )}
          </div>
        </div>
      </nav>

      <main
        className="flex-grow flex flex-col items-center justify-center relative pb-20 overflow-hidden"
        data-oid="2bcntoq"
      >
        <div className="absolute inset-0 z-0" data-oid="ck-pgil">
          <SoftAurora
            speed={0.6}
            scale={1.5}
            brightness={0.5}
            color1="#f1f1f1"
            color2="#2dd2ffa4"
            noiseFrequency={2.5}
            noiseAmplitude={1.0}
            bandHeight={0.5}
            bandSpread={1.0}
            octaveDecay={0.1}
            layerOffset={0}
            colorSpeed={1.0}
            enableMouseInteraction={true}
            mouseInfluence={0.25}
            data-oid="fb8blku"
          />
        </div>

        <div
          className="w-full max-w-3xl px-gutter text-center relative z-10"
          data-oid="-3-lwjt"
        >
          <h1
            className="text-display font-display text-on-surface mb-4 tracking-tight"
            data-oid="8hlgofg"
          >
            <span className="text-primary" data-oid="9i.gvu0">
              {t("page:upload.title")}
            </span>
          </h1>
          <p
            className="text-body-lg text-on-surface-variant mb-12 opacity-80"
            data-oid="ymstsg2"
          >
            {t("page:upload.subtitle")}
          </p>

          <form onSubmit={handleUpload} data-oid="niq-ecy">
            <label
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className="group relative bg-surface border border-outline-variant/60 rounded-[32px] p-2 shadow-2xl shadow-primary/5 hover:shadow-primary/10 transition-all duration-500 block cursor-pointer"
              data-oid="7yg61ns"
            >
              <div
                className="border-2 border-dashed border-outline-variant/40 group-hover:border-primary/40 rounded-[24px] p-16 flex flex-col items-center justify-center transition-colors bg-surface-container-lowest"
                data-oid="k0b6a:s"
              >
                <div
                  className="w-20 h-20 bg-primary-container/10 rounded-full flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300"
                  data-oid="ajy0mhu"
                >
                  <FileUp
                    className="text-primary"
                    size={48}
                    data-oid="px3ycbc"
                  />
                </div>
                <h3
                  className="text-headline-md font-medium text-on-surface mb-2"
                  data-oid="kfvj3:1"
                >
                  {t("page:upload.dropText")}
                </h3>
                <p className="text-body-md text-outline" data-oid="t9dp-6m">
                  {t("page:upload.fileTypes")}
                </p>
                <div
                  className="mt-8 flex items-center gap-3"
                  data-oid="gpse438"
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById("file-input").click();
                    }}
                    className="px-6 py-3 bg-primary text-on-primary rounded-full font-headline-md hover:bg-primary-container transition-all shadow-md"
                    data-oid="6u.0jiv"
                  >
                    {t("page:upload.selectFiles")}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById("folder-input").click();
                    }}
                    className="px-6 py-3 border border-outline-variant text-on-surface rounded-full font-headline-md hover:bg-surface-container transition-all"
                    data-oid="dugttge"
                  >
                    {t("page:upload.selectFolder")}
                  </button>
                </div>
                <input
                  id="file-input"
                  type="file"
                  multiple
                  className="hidden"
                  accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                  data-oid=":44.eff"
                />

                <input
                  id="folder-input"
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  className="hidden"
                  accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                  data-oid="bxhd.0g"
                />
              </div>
            </label>

            {files.length > 0 && (
              <div
                className="mt-4 bg-white rounded-xl border border-outline-variant p-4 text-left max-w-xl mx-auto"
                data-oid="b2ac229"
              >
                <p
                  className="text-sm font-medium text-on-surface mb-2"
                  data-oid="j9e_0bd"
                >
                  {t("page:upload.selectedFiles")}
                </p>
                <ul
                  className="text-sm text-on-surface-variant space-y-1"
                  data-oid="4v-defg"
                >
                  {files.map((f, i) => (
                    <li
                      key={i}
                      className="flex items-center gap-2"
                      data-oid="tanzmal"
                    >
                      <span
                        className="bg-surface-container px-2 py-0.5 rounded"
                        data-oid="zkzin0y"
                      >
                        {f.name}
                      </span>
                      {f.webkitRelativePath && (
                        <span
                          className="text-outline text-xs truncate max-w-xs"
                          title={f.webkitRelativePath}
                          data-oid="lej1mlm"
                        >
                          {f.webkitRelativePath}
                        </span>
                      )}
                      <span data-oid="u7_44rm">
                        ({(f.size / 1024 / 1024).toFixed(2)} MB)
                      </span>
                    </li>
                  ))}
                </ul>
                {error && (
                  <p className="text-red-600 text-sm mt-3" data-oid="taxgsq2">
                    {error}
                  </p>
                )}
                <div className="flex gap-3 mt-4" data-oid="b29308x">
                  <button
                    type="button"
                    onClick={() => setFiles([])}
                    className="flex-1 border border-outline-variant rounded-lg py-2.5 text-sm font-medium hover:bg-surface-container transition-colors"
                    data-oid="yprb_h9"
                  >
                    {t("page:upload.cancel")}
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                    data-oid="d565dfv"
                  >
                    {submitting ? (
                      <>
                        <Loader2
                          className="animate-spin"
                          size={18}
                          data-oid="9svg__2"
                        />{" "}
                        {t("page:upload.uploading")}
                      </>
                    ) : (
                      t("page:upload.start")
                    )}
                  </button>
                </div>
              </div>
            )}
          </form>

          <div
            className="mt-8 flex justify-center gap-8 text-label-sm text-outline font-medium uppercase tracking-widest opacity-60"
            data-oid="76kls65"
          >
            <span className="flex items-center gap-1.5" data-oid="0-qp_fh">
              <span className="text-sm" data-oid="1igwucs">
                {t("page:upload.badgeSecurity")}
              </span>{" "}
              {t("page:upload.badgeEncrypted")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="kqvvz4f">
              <span className="text-sm" data-oid="5:pkdv_">
                {t("page:upload.badgeInstant")}
              </span>{" "}
              {t("page:upload.badgeProcessing")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="qb:09.m">
              <span className="text-sm" data-oid="_6x3:bb">
                100+
              </span>{" "}
              {t("page:upload.badgeLanguages")}
            </span>
          </div>
        </div>
      </main>

      <footer
        className="w-full py-8 border-t border-outline-variant/20"
        data-oid="d_e-cym"
      >
        <div
          className="max-w-container-max mx-auto px-gutter flex flex-col md:flex-row justify-between items-center gap-4 text-label-sm text-outline"
          data-oid="r3q1:wf"
        >
          <div className="flex items-center gap-4" data-oid="klyxm2c">
            <p data-oid="1t6lh6f">{t("page:upload.copyright")}</p>
          </div>
          <div className="flex items-center gap-6" data-oid="931pbx.">
            <Link
              to="/developer"
              className="hover:text-primary transition-colors"
              data-oid="nldn860"
            >
              {t("page:upload.api")}
            </Link>
            <a
              href="/admin"
              className="hover:text-primary transition-colors"
              data-oid="x2l5zmm"
            >
              {t("page:upload.admin")}
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
