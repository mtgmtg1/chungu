// [Flow: Step 1 (로그인 확인) -> Step 2 (중앙 업로드 영역) -> Step 3 (init -> TUS 업로드 -> create) -> Step 4 (비용 확인 페이지 이동)]
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileUp, Loader2, LogIn, Coins } from "lucide-react";
import GridScan from "../components/GridScan.jsx";
import { AnimatedRow } from "../components/AnimatedList.jsx";
import { useAuth } from "../AuthContext.jsx";
import { api } from "../api.js";
import { uploadFilesTUS } from "../tusUpload.js";

export default function UploadPage() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const nav = useNavigate();
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");
  const [doclingRefinement, setDoclingRefinement] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0, percent: 0, fileName: "" });

  useEffect(() => {
    if (!user) return;
    api.
    me().
    then(setProfile).
    catch(() => {});
  }, [user]);

  async function traverseEntry(entry, collected, basePath = "") {
    if (entry.isFile) {
      const file = await new Promise((resolve) => entry.file(resolve));
      file.webkitRelativePath = basePath + file.name;
      collected.push(file);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries = await new Promise((resolve) =>
      reader.readEntries(resolve)
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

    setSubmitting(true);
    try {
      // Step 1: init - 임시 Job 생성 + Storage 경로 할당
      const filesPayload = files.map((f) => ({
        name: f.name,
        size: f.size,
        relative_path: f.webkitRelativePath || f.name,
      }));

      const initRes = await api.initJob({
        files: filesPayload,
        docling_refinement: doclingRefinement,
      });

      // Step 2: TUS 청크 업로드 (각 청크 6MB, Cloudflare 100MB 제한 회피)
      const uploadItems = files.map((f, i) => ({
        file: f,
        storagePath: initRes.upload_paths[i].storage_path,
      }));

      setUploadProgress({ current: 0, total: files.length, percent: 0, fileName: files[0]?.name || "" });

      await uploadFilesTUS(
        uploadItems,
        (fileIndex, pct) => {
          setUploadProgress({
            current: fileIndex,
            total: files.length,
            percent: pct,
            fileName: files[fileIndex]?.name || "",
          });
        },
      );

      // Step 3: create - Storage 파일 분석 + 비용 계산
      const createPayload = {
        files: initRes.upload_paths.map((p) => ({
          storage_path: p.storage_path,
          original_name: p.original,
          relative_path: p.relative_path,
        })),
      };

      const res = await api.createJob(initRes.job_id, createPayload);
      nav(`/jobs/${res.job_id}/confirm`);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
      setUploadProgress({ current: 0, total: 0, percent: 0, fileName: "" });
    }
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" data-oid="fb1q5zd">
        <Loader2 className="animate-spin text-primary" size={32} data-oid="ohz8:m:" />
      </div>);

  }

  return (
    <div className="min-h-screen bg-background text-on-background flex flex-col overflow-x-hidden" data-oid="23_u4l8">
      <nav className="w-full bg-transparent" data-oid="i7-y4-o">
        <div className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter" data-oid="2gdjtc9">
          <div className="flex items-center gap-2" data-oid="ro0013g">
            <span className="font-headline-md text-headline-md font-bold text-primary tracking-tight" data-oid="9p74bh1">
              Chungu File
            </span>
          </div>
          <div className="flex items-center gap-6" data-oid="azbdxm0">
            {user ?
            <>
                <Link
                to="/dashboard"
                className="text-body-md text-on-surface-variant hover:text-primary transition-colors font-medium" data-oid="hxfwqj4">

                  {t("page:upload.myJobs")}
                </Link>
                <Link
                to="/payment"
                className="text-body-md flex items-center gap-1 text-primary hover:underline font-medium" data-oid="j8k1rq5">

                  <Coins size={18} data-oid="w8q2nfw" /> {profile?.points_balance ?? "-"}{" "}
                  {t("page:upload.points")}
                </Link>
              </> :

            <Link
              to="/login"
              className="text-body-md flex items-center gap-1 text-on-surface-variant hover:text-primary transition-colors font-medium" data-oid="4bqhh5q">

                <LogIn size={18} data-oid="n24csz4" /> {t("common:auth.login")}
              </Link>
            }
          </div>
        </div>
      </nav>

      <main className="flex-grow flex flex-col items-center justify-center relative pb-20 overflow-hidden" data-oid="hukjmb5">
        <div className="absolute inset-0 z-0" data-oid="6iwhhjt">
          <GridScan
            sensitivity={0.55}
            lineThickness={1}
            linesColor="#2f293a"
            gridScale={0.1}
            lineJitter={0}
            scanColor="#3b82f6"
            scanOpacity={0.4}
            scanGlow={0.5}
            scanSoftness={2}
            enablePost={false}
            chromaticAberration={0.002}
            noiseIntensity={0.01} data-oid="8h972jn" />

        </div>

        <div className="w-full max-w-3xl px-gutter text-center relative z-10" data-oid="t:1j9cg">
          <h1 className="text-display font-display text-on-surface mb-4 tracking-tight" data-oid="icit2z9">
            <span className="text-primary" data-oid="9zubavq">{t("page:upload.title")}</span>
          </h1>
          <p className="text-body-lg text-on-surface-variant mb-12 opacity-80" data-oid="0lczkhk">
            {t("page:upload.subtitle")}
          </p>

          <form onSubmit={handleUpload} data-oid="uhu483v">
            <label
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className="group relative bg-surface border border-outline-variant/60 p-2 shadow-2xl shadow-primary/5 hover:shadow-primary/10 transition-all duration-500 block cursor-pointer" data-oid="lu0z:ql">

              <div className="border-2 border-dashed border-outline-variant/40 group-hover:border-primary/40 p-12 flex flex-col items-center justify-center transition-colors bg-surface-container-lowest" data-oid="edljjr1">
                <div className="w-16 h-16 bg-primary-container/10 flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300" data-oid=":jtd.dp">
                  <FileUp className="text-primary" size={40} data-oid="t2qzlm3" />
                </div>
                <h3 className="text-headline-md font-medium text-on-surface mb-2" data-oid="i-mqa2a">
                  {t("page:upload.dropText")}
                </h3>
                <p className="text-body-md text-outline" data-oid="qx:xw_:">
                  {t("page:upload.fileTypes")}
                </p>
                <div className="mt-8 flex items-center gap-3" data-oid="9pgvpvb">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById("file-input").click();
                    }}
                    className="px-5 py-2.5 bg-primary text-on-primary font-headline-md hover:bg-primary-container transition-all shadow-md" data-oid="y:11dj9">

                    {t("page:upload.selectFiles")}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById("folder-input").click();
                    }}
                    className="px-5 py-2.5 border border-outline-variant text-on-surface font-headline-md hover:bg-surface-container transition-all" data-oid="4ck0s7w">

                    {t("page:upload.selectFolder")}
                  </button>
                </div>
                <input
                  id="file-input"
                  type="file"
                  multiple
                  className="hidden"
                  accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.html,.htm,.hwp,.hwpx"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))} data-oid="kc2h.f3" />


                <input
                  id="folder-input"
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  className="hidden"
                  accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.html,.htm,.hwp,.hwpx"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))} data-oid="vf8-08s" />

              </div>
            </label>

            {files.length > 0 &&
            <div className="mt-4 bg-white border border-outline-variant p-3 text-left max-w-xl mx-auto" data-oid="xcv5knj">
                <p className="text-sm font-medium text-on-surface mb-2" data-oid="y_ncx1w">
                  {t("page:upload.selectedFiles")}
                </p>
                <ul className="text-sm text-on-surface-variant space-y-1" data-oid=".1zu2a:">
                  {files.map((f, i) =>
                <AnimatedRow key={i} index={i}>
                <li className="flex items-center gap-2" data-oid="pj8ozgj">
                      <span className="bg-surface-container px-2 py-0.5" data-oid="v5ru_8d">
                        {f.name}
                      </span>
                      {f.webkitRelativePath &&
                  <span
                    className="text-outline text-xs truncate max-w-xs"
                    title={f.webkitRelativePath} data-oid="aayyxtt">

                          {f.webkitRelativePath}
                        </span>
                  }
                      <span data-oid="d52i72h">({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
                    </li>
                </AnimatedRow>
                )}
                </ul>
                {error && <p className="text-red-600 text-sm mt-3" data-oid="-a7o5g0">{error}</p>}
                {submitting && uploadProgress.total > 0 && (
                  <div className="mt-3 mb-2" data-oid="upload-progress">
                    <div className="flex items-center justify-between text-xs text-on-surface-variant mb-1">
                      <span className="truncate max-w-[200px]" data-oid="prog-file">
                        {uploadProgress.fileName}
                      </span>
                      <span data-oid="prog-count">
                        {uploadProgress.current + 1}/{uploadProgress.total} ({uploadProgress.percent}%)
                      </span>
                    </div>
                    <div className="w-full bg-surface-container h-2 overflow-hidden" data-oid="prog-bar-bg">
                      <div
                        className="bg-primary h-full transition-all duration-300"
                        style={{ width: `${uploadProgress.percent}%` }}
                        data-oid="prog-bar-fill"
                      />
                    </div>
                  </div>
                )}
                <div className="flex gap-3 mt-4" data-oid="sj37fh-">
                  <button
                  type="button"
                  onClick={() => setFiles([])}
                  className="flex-1 border border-outline-variant rounded-lg py-2.5 text-sm font-medium hover:bg-surface-container transition-colors" data-oid="d:b_931">

                    {t("page:upload.cancel")}
                  </button>
                  <button
                  type="submit"
                  disabled={submitting}
                  className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2" data-oid="0rnk870">

                    {submitting ?
                  <>
                        <Loader2 className="animate-spin" size={18} data-oid="trpaow-" />{" "}
                        {t("page:upload.uploading")}
                      </> :

                  t("page:upload.start")
                  }
                  </button>
                </div>
              </div>
            }
          </form>

          <div className="mt-8 flex justify-center gap-8 text-label-sm text-outline font-medium uppercase tracking-widest opacity-60" data-oid="10-kc.x">
            <span className="flex items-center gap-1.5" data-oid="dtoqnz9">
              <span className="text-sm" data-oid="bqnxyd_">{t("page:upload.badgeSecurity")}</span>{" "}
              {t("page:upload.badgeEncrypted")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="1ob4op1">
              <span className="text-sm" data-oid="mfc0llf">{t("page:upload.badgeInstant")}</span>{" "}
              {t("page:upload.badgeProcessing")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="q6ff538">
              {" "}
              {t("page:upload.badgeLanguages")}
            </span>
          </div>
        </div>
      </main>

      <footer className="w-full py-8 border-t border-outline-variant/20" data-oid="tcsqbqv">
        <div className="max-w-container-max mx-auto px-gutter flex flex-col md:flex-row justify-between items-center gap-4 text-label-sm text-outline" data-oid="nxq6d5t">
          <div className="flex items-center gap-4" data-oid="vblxy38">
            <p data-oid="zwnm7_d">{t("page:upload.copyright")}</p>
          </div>
          <div className="flex items-center gap-6" data-oid="2.0d1h3">
            <Link
              to="/developer"
              className="hover:text-primary transition-colors" data-oid="6zrgl05">

              {t("page:upload.api")}
            </Link>
            <a href="/admin" className="hover:text-primary transition-colors" data-oid="i457pgw">
              {t("page:upload.admin")}
            </a>
          </div>
        </div>
      </footer>
    </div>);

}