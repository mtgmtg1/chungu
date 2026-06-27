# Docling Preprocessing Pipeline

Chungu uses IBM Docling as the first-stage preprocessor for structured documents (PDF, DOCX, PPTX, XLSX, HTML). Docling extracts native text, tables, and images into a structured markdown representation, reducing the load on the downstream vision LLM.

## Supported Input Types

- `pdf` — processed by the Docling PDF pipeline (CPU + VNNI/OneDNN on Intel Xeon).
- `docx`, `doc`, `dotx`, `docm` — Word documents via the Docling MS Word backend.
- `pptx`, `ppt`, `potx`, `ppsx`, `pptm`, `potm`, `ppsm` — PowerPoint presentations.
- `xlsx`, `xls`, `xlsm` — Excel spreadsheets.
- `html`, `htm`, `xhtml` — HTML documents.

HWP/HWPX files are handled by a separate converter (see [HWP Support](./hwp.md)).

## Architecture

1. The user uploads one or more files to the a1 backend.
2. The backend detects file types and routes Docling-compatible files to the Docling service.
3. The Docling service converts each file to a `DoclingDocument`, exports markdown with image placeholders, and extracts embedded images.
4. The backend receives the markdown and image paths.
5. If **Docling refinement** is enabled, the backend downloads the images and sends the markdown + images to the media LLM for layout-aware cleanup.
6. The final structured output is converted to CSV, XLSX, Markdown, or DOCX/PPTX.

## Docling Service (CPU/VNNI)

The Docling service runs as a standalone FastAPI container on the document-preprocessing server. On the Xeon Scalable 6230 dual-socket host, the service is tuned for Intel VNNI/AVX-512 inference using the CPU PyTorch wheel and Intel Extension for PyTorch (IPEX).

### Base image and dependencies

- `ubuntu:22.04` base image.
- `torch==2.3.1+cpu` and `torchvision==0.18.1+cpu` installed from the PyTorch CPU wheel index.
- `intel-extension-for-pytorch==2.3.1+cpu` for OneDNN graph optimization.
- `numactl` installed in the container for NUMA binding.

### Runtime environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `DOCLING_NUM_THREADS` | `20` | Number of CPU threads per pipeline. Set to one socket's physical core count. |
| `DOCLING_LAYOUT_BATCH_SIZE` | `16` | Layout model batch size. Can be increased on VNNI-enabled CPUs. |
| `DOCLING_TABLE_BATCH_SIZE` | `4` | Table structure model batch size. |
| `DOCLING_OCR_BATCH_SIZE` | `4` | OCR batch size (currently disabled with `do_ocr=false`). |
| `DOCLING_SERVICE_PORT` | `28182` | FastAPI listening port. |

### NUMA / numactl binding

The Xeon 6230 dual-socket setup has two NUMA nodes. To avoid UPI latency between sockets, bind each Docling worker to a single NUMA node and run two independent workers in parallel for maximum throughput.

```bash
# Worker 1: socket 0
export OMP_NUM_THREADS=20
export MKL_NUM_THREADS=20
numactl --cpunodebind=0 --membind=0 \
  docker compose -f docker-compose.docling.yml up -d

# Worker 2: socket 1 (change host port and compose project name)
export DOCLING_SERVICE_PORT=28183
export COMPOSE_PROJECT_NAME=docling_socket1
numactl --cpunodebind=1 --membind=1 \
  docker compose -f docker-compose.docling.yml up -d
```

For a single worker on a single socket, use:

```bash
numactl --cpunodebind=0 --membind=0 \
  docker compose -f docker-compose.docling.yml up -d
```

### VNNI verification

Inside the container, verify VNNI is available through PyTorch OneDNN:

```python
import torch
print(torch.__config__.show())
# Look for AVX512_VNNI and oneDNN entries.
```

## Backend Integration

The a1 backend connects to the Docling service via `core/docling_client.py`:

- `docling_client.convert_file(path)` uploads a file and returns markdown, image paths, and estimated page count.
- `docling_client.download_image(path)` fetches extracted image bytes.
- `docling_client.health_check()` verifies service availability.

The `DOCLING_SERVICE_URL` and `DOCLING_ENABLED` settings are managed in `settings_store` (or via `.env`).

## Docling Refinement (LLM Post-processing)

When a user enables refinement, the backend downloads the extracted images and calls the media LLM endpoint with the markdown and a layout-cleanup prompt. This costs an additional `cost_per_docling_refinement_page_krw` per page.

Refinement is controlled by:

- `use_docling_refinement` per-job flag.
- `docling_refinement_enabled` global setting.
- `docling_max_images_per_doc` — max images sent to the LLM per document.
- `docling_image_max_size` — max long-edge dimension for extracted images.

## Deployment Checklist

1. Build the CPU image on the preprocessing server:
   ```bash
   cd app
   docker compose -f docker-compose.docling.yml build
   ```
2. Apply the DB migration:
   ```bash
   psql $DATABASE_URL -f app/backend/db/migrations/006_add_docling_refinement.sql
   ```
3. Start the service with NUMA binding.
4. Verify health:
   ```bash
   curl http://<docling-host>:28182/health
   ```
5. Run `test_docling_service.py` and `test_backend_docling.py`.
