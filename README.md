# Adobe-India-Hackathon25
# PDF Heading Extraction Tool

This tool automatically extracts document titles and heading outlines from PDF files, outputting structured JSON data for each processed document.

## Approach

The solution uses a multi-layered approach to extract meaningful headings from PDF documents:

### 1. **Primary Method: TOC Extraction**
- First attempts to extract the built-in Table of Contents (TOC) from PDF metadata
- If available, uses this as the authoritative heading structure

### 2. **Fallback Method: Heuristic-Based Detection**
When no TOC is available, the system employs sophisticated heuristics:

- **Language Detection**: Uses language identification to apply appropriate text processing rules
- **Font Analysis**: Identifies headings based on font size, weight (bold), and style differences
- **Body Text Analysis**: Determines the most common font size as baseline body text
- **Context Validation**: Ensures detected headings are followed by appropriate body content
- **Style Matching**: Finds additional headings with similar formatting

### 3. **Document Title Extraction**
- Analyzes the first page to identify the document title
- Uses font size and positioning heuristics
- Applies multiple strategies (strict and flexible) for optimal results

### 4. **Hierarchy Validation**
- Ensures proper heading level progression (H1 → H2 → H3 → H4)
- Fixes broken hierarchies automatically
- Maintains logical document structure

### 5. **Multi-Language Support**
- **Latin scripts**: Word-based counting and processing
- **CJK languages** (Chinese, Japanese, Korean, Thai): Character-based processing
- **Indic languages**: Specialized handling for Hindi, Bengali, Marathi, etc.

## Libraries and Models Used

### Core Dependencies
- **PyMuPDF (fitz)**: PDF parsing and text extraction
- **langid**: Automatic language detection for text processing
- **unicodedata**: Unicode text normalization and categorization

### Standard Libraries
- **json**: Output formatting
- **re**: Text pattern matching
- **pathlib**: File system operations
- **collections.Counter**: Statistical text analysis

### Key Features
- Font style analysis (size, bold, italic, font family)
- Unicode-aware text processing
- Configurable parameters for different document types
- Robust error handling and validation

## Configuration

The tool includes configurable parameters in the `CONFIG` dictionary:

```python
CONFIG = {
    "HEADING_SIZE_FACTOR": 1.05,      # Minimum size ratio for headings
    "HEADER_FOOTER_MARGIN": 0.00,     # Margin to ignore headers/footers
    "MAX_HEADING_LEVELS": 4,          # Maximum heading depth (H1-H4)
    "BODY_SIZE_MIN_TEXT_LEN_*": 5,    # Minimum text length by language
    "HEADING_MAX_WORDS": 30,          # Maximum words in a heading
    "TITLE_MAX_WORDS": 35,            # Maximum words in document title
}
```

## How to Build and Run

### Building the Docker Image
```bash
docker build --platform linux/amd64 -t mysolutionname:somerandomidentifier .
```

### Running the Solution
```bash
docker run --rm -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output --network none mysolutionname:somerandomidentifier
```

### Expected Behavior
1. **Input**: The container reads all PDF files from `/app/input` directory
2. **Processing**: For each `filename.pdf`, extracts title and heading outline
3. **Output**: Generates corresponding `filename.json` in `/app/output` directory

### Output Format
Each JSON file contains:
```json
{
    "title": "Document Title",
    "outline": [
        {
            "level": "H1",
            "text": "Chapter 1: Introduction",
            "page": 0
        },
        {
            "level": "H2", 
            "text": "1.1 Background",
            "page": 1
        }
    ]
}
```

## Algorithm Workflow

1. **Document Analysis**: Open PDF and analyze text structure
2. **Language Detection**: Identify document language for appropriate processing
3. **Title Extraction**: Find document title from first page
4. **TOC Check**: Attempt to extract built-in table of contents
5. **Heuristic Analysis**: If no TOC, use font and context analysis
6. **Validation**: Verify headings exist in document text
7. **Hierarchy Fix**: Ensure proper heading level progression
8. **Output**: Save structured JSON with title and outline

## Error Handling

- Graceful handling of corrupted or unreadable PDFs
- Fallback mechanisms when primary extraction methods fail
- Validation to ensure extracted headings actually exist in the document
- Protection against false positives (copyright notices, headers/footers, etc.)

The solution is designed to be robust and work across various PDF types, from academic papers to technical manuals, with automatic adaptation based on document language and structure.