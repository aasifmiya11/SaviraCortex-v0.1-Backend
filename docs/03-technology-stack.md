# 3. Technology Stack

## 3.1 Runtime and packaging

- Python requirement: `>=3.11` as declared in `pyproject.toml`.
- Package/project name: `voice-ai`, version `0.1.0`.
- Dependency lock: `uv.lock`.
- Test runner: pytest; pytest configuration is in `pyproject.toml`.

## 3.2 Main declared dependencies

| Technology/package | Declared role in this codebase |
|---|---|
| SQLAlchemy | ORM, relational models, sessions and schema creation |
| psycopg / psycopg2-binary | PostgreSQL drivers |
| redis | Async Redis-compatible client |
| boto3 | S3-compatible Backblaze B2 access |
| Qdrant integrations | Vector database client and LangChain integration |
| langchain, langchain-community | Document abstractions and LLM/RAG composition |
| langchain-openai | Chat model adapter |
| langgraph | Graph-based agent execution |
| langchain-huggingface | Hugging Face embedding integration |
| sentence-transformers | Embedding/reranking model ecosystem |
| langchain-text-splitters | Text chunking |
| PyMuPDF (pymupdf) | Native PDF parsing/rendering |
| EasyOCR, pytesseract, langchain-fastocr | OCR-related options/adapters |
| pydantic | Structured model validation and LLM output parsing |
| python-dotenv | Load environment variables from dotenv files |
| FastAPI | Declared dependency; no implemented routes were found in the reviewed API directory |
| FAISS CPU | Declared dependency; not established as the active production vector store by this review |
| pandas, Pillow, unstructured | Declared supporting libraries; usage varies by module |

## 3.3 LLM integration

The LLM clients construct `ChatOpenAI` instances using `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY`. Separate client classes provide different defaults for summarization, retrieval and multi-query generation. A compatible API endpoint may be configured through the base URL; the actual provider/model is environment-dependent.

## 3.4 Vector and embedding layer

Qdrant is the vector database integration used by the RAG modules. The project includes a Hugging Face embedding adapter and Qdrant-specific payload index and summary-store helpers. Model identifiers and vector dimensions must be taken from the implementation/configuration in the deployed environment; they should not be guessed from package names.

## 3.5 OCR layer

The PDF reader supports native text extraction and OCR strategies. Configuration exposes OCR engine/language selection, render DPI, minimum native text characters, whether all pages should be OCR-processed, and whether OCR output should be merged with native text. The concrete engine availability depends on local system packages and credentials.

## 3.6 Testing stack

pytest is configured with the repository root on `pythonpath`. The `integration` marker identifies tests that need external services or integration infrastructure. Tests include unit/service, agent, RAG, integration and end-to-end categories.

## 3.7 Dependency declaration versus runtime usage

A dependency being present in `pyproject.toml` does not prove that the package is used by the current execution path. This documentation distinguishes directly visible integrations from packages that are only declared.
