# AI Laboratory for Scientific Research

A virtual laboratory of AI agents designed to facilitate collaborative scientific research discussions and planning. This project is a very rough prototype.

> **Note on Paper Access**: The bioRxiv search functionality is limited and sometimes unstable due to API constraints. To address this limitation, a new `/read_folder` command has been added, allowing agents to read and discuss papers from a local folder. This provides a more reliable alternative when online searches don't return the desired results.

## Overview

This project creates a terminal-based application that simulates a laboratory environment with multiple AI agents, each with different specialties. The lab provides a space for:

- Collaborative discussions among AI agents and users
- Analysis of scientific papers and documents
- Research planning and ideation
- Cross-disciplinary knowledge synthesis
- Formalized multi-round discussions on focused topics

## Features

- **Multi-Agent Environment**: Create a customizable team of AI expert agents with different specialties
- **Direct Messaging**: Address specific agents using @mention syntax
- **Research Analysis**: Analysis of scientific papers and research topics
- **Enhanced Collaboration**: Agents directly engage with each other and follow up on questions
- **Visual Conversation Mapping**: Track inter-agent communication patterns
- **Structured Discussions**: Run formal multi-round discussions on specific topics
- **Research Integration**: Connect to arXiv and bioRxiv for paper summaries
- **Highly Customizable**: Configure agents, specialties, and personalities via YAML

## Installation

1. Clone this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Before running the application, set up your configuration file:

1. Copy the example configuration file:
   ```bash
   cp config.yaml.example config.yaml
   ```

2. Edit the `config.yaml` file:
   - Keep your Anthropic API key for Ada (Claude)
   - Fill missing values in `api_keys.groq`, `api_keys.qwen`, `api_keys.zhipu`, and `api_keys.gemini`
   - Lea uses GPT-OSS-120B on Groq; Emmy uses Gemini 3.8 Flash on Google; Marie uses GLM-4.7-Flash on BigModel; Qwen uses DashScope (Beijing)
   - Customize your user name
   - Modify the AI agents and their specialties if desired

See [the five-model setup guide](MULTI_MODEL_SETUP.md) for model assignments,
key locations, environment variables, and limitations. Each agent now has
its own `provider` and `model`. Optional `system_prompt` instructions apply to
every response workflow. Legacy single-Anthropic and NVIDIA configurations still work.

Check configuration without making API calls:

```bash
python -m src.main --config config.yaml --check-config
```

To get an Anthropic API key:
1. Go to https://console.anthropic.com/
2. Sign up or log in to your account
3. Navigate to the API Keys section
4. Create a new API key
5. Copy the key and paste it in your config.yaml file

## Usage

Run the application with:

```bash
python -m src.main --config config.yaml
```

### Interaction Features

- **Regular Discussion**: Type messages normally to engage all agents
- **Direct Messaging**: Use `@AgentName:` at the beginning of a line to address specific agents
- **Structured Discussions**: Type `/discuss <topic>` to initiate a focused multi-round discussion

### Example Interaction

```
=== Welcome to the AI Laboratory, Erin! ===

Your AI research team:
  Lea (Biologist): Expert in molecular biology, genetics, and biochemical pathways.
  Emmy (Mathematician): Specialist in statistical analysis and complex data modeling.
  Marie (Physicist): Expert in quantum mechanics and simulation.
  Ada (Computer Scientist): Specialist in machine learning and algorithms.
  Cassandra (PI): As the lab director, guides discussions and integrates perspectives.

=== Instructions ===
• Type your message and press Enter to start the discussion
• To address specific agents directly, use '@AgentName:' at the start of a line
• Type '/discuss <topic>' to start a focused multi-round agent discussion
• Type '/search <query> [--type arxiv|biorxiv] [--results <number>] [--months <number>]' to search for information
  - For bioRxiv searches, use '--months' to specify how many months back to search (default: 12)
• Type '/read_folder <folder_path>' to have agents read and discuss papers in a local folder
• Type '/cost' to see estimated API costs of the current session
• Type 'exit' to end the session

=== Beginning of Discussion ===

Erin:
  /search protein language models --type biorxiv --results 3

🔍 Searching biorxiv for: protein language models

✅ Search Results (3 found)

1. Pre-trained protein language model for codon optimization
   https://www.biorxiv.org/content/10.1101/2024.12.12.628267v2
   Published: 2024-12-12

2. Protein Language Model Identifies Disordered, Conserved Motifs Driving Phase Separation
   https://www.biorxiv.org/content/10.1101/2024.12.12.628175v1
   Published: 2024-12-12

3. ProDualNet: Dual-Target Protein Sequence Design Method Based on Protein Language Model and Structure Model
   https://www.biorxiv.org/content/10.1101/2025.02.28.640919v1
   Published: 2025-02-28

Type 'continue' to have agents download, read the full text, and discuss these papers in depth.

Erin:
  continue

🧠 Starting in-depth discussion of search results...

🔍 Agent roles assigned:
   Reader agents: Emmy, Lea
   Questioner agents: Marie, Ada, Cassandra

📚 2 agents are reviewing 3 papers while 3 agents will ask questions...

┌─── Emmy ────────────────────────────────────────────────────────────────────────┐
│ Alright, so I've just finished reading through a couple of really interesting    │
│ papers that I think you all might want to hear about.                            │
│ The first one is "ProDualNet: Dual-Target Protein Sequence Design Method Based   │
│ on Protein Language Model and Structure Model" by Liu Cheng and colleagues. It's │
│ a fresh preprint from late February this year.                                   │
│ The second paper is "Protein Language Model Identifies Disordered, Conserved     │
│ Motifs Driving Phase Separation" by Yumeng Zhang and team, which came out in     │
│ December.                                                                        │
│ Let's start with the ProDualNet paper. What caught my eye here is how they're    │
│ combining protein language models with structure models for protein design.      │
│ They've developed this method that can generate sequences that satisfy both      │
│ sequence-based and structure-based constraints simultaneously. It's pretty       │
│ clever - they're using a transformer-based language model for the sequence part  │
│ and AlphaFold2 for the structure predictions.                                    │
└──────────────────────────────────────────────────────────────────────────────────┘

┌─── Lea ─────────────────────────────────────────────────────────────────────────┐
│ Alright, so I've just finished reading this paper titled "Pre-trained protein    │
│ language model for codon optimization" by Pathak and Lin. It's a pretty          │
│ interesting piece that dives into using language models for codon optimization   │
│ in protein synthesis.                                                            │
│ The main thing that caught my attention is how they're applying techniques from  │
│ natural language processing to biological sequences. They've developed this      │
│ model called PALM-CO that's pre-trained on a massive dataset of protein          │
│ sequences and then fine-tuned for codon optimization tasks.                      │
│ What's cool is that they're not just looking at individual codons in isolation,  │
│ but considering the broader sequence context. Their model takes into account     │
│ things like codon pair bias and GC content, which can have a big impact on       │
│ protein expression levels.                                                       │
└──────────────────────────────────────────────────────────────────────────────────┘

┌─── Marie ───────────────────────────────────────────────────────────────────────┐
│ @Emmy: I'm intrigued by the ProDualNet paper's approach to balancing sequence    │
│ and structure constraints. Have they discussed how sensitive their results are   │
│ to the weighting between these two objectives? I'm wondering if there's a risk   │
│ of overfitting to one aspect at the expense of the other, especially given the   │
│ computational complexity of structural predictions.                              │
└────────────────────────────────────────────────────────────────[ To: Emmy ]─┘

┌─── Emmy ────────────────────────────────────────────────────────────────────────┐
│ @Marie: Great question about the ProDualNet paper! They actually do address some │
│ of your concerns, though not exhaustively. The authors used a weighted sum of    │
│ sequence and structure losses, with weights of 1 and 0.5 respectively. They      │
│ found this balance worked well, but you're right to wonder about sensitivity -   │
│ they don't report extensive experiments varying these weights.                   │
│ On overfitting, they employed early stopping based on validation loss to         │
│ mitigate this risk. However, they don't deeply explore potential tradeoffs       │
│ between sequence and structure optimization. It's a valid concern that           │
│ optimizing too heavily for one aspect could come at the expense of the other.    │
└─────────────────────────────────────────────────────────────────[ To: Marie ]─┘

┌─── Cassandra ───────────────────────────────────────────────────────────────────┐
│ Thanks everyone for the great discussion on these fascinating papers. I think    │
│ we've covered a lot of ground here.                                              │
│ To recap, we looked at "ProDualNet: Dual-Target Protein Sequence Design Method   │
│ Based on Protein Language Model and Structure Model", "Protein Language Model    │
│ Identifies Disordered, Conserved Motifs Driving Phase Separation", and           │
│ "Pre-trained protein language model for codon optimization".                     │
│ A few key insights emerged:                                                      │
│ 1. The ProDualNet paper's approach of using weighted losses to balance sequence  │
│ and structure constraints is intriguing, but as @Emmy pointed out, we should be  │
│ cautious about how robust this 1:0.5 weighting is across diverse protein         │
│ families.                                                                        │
│ 2. The PALM-CO model for codon optimization considers broader sequence context,  │
│ which @Lea highlighted could have interesting applications in protein            │
│ engineering. However, its applicability to non-natural amino acids remains an    │
│ open question.                                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Architecture and Design

The codebase follows a modular structure:

- `src/`: Main source code
  - `agents/`: Contains agent-related code
    - `base.py`: Base agent implementation with conversation capabilities
    - `lab.py`: Laboratory implementation managing multi-agent interactions
  - `config/`: Configuration handling
  - `utils/`: Utility functions including paper retrieval
  - `main.py`: Application entry point

This project was developed with the assistance of Claude Code.

## Comparison with AgentLaboratory

This project is inspired by [AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) but takes a different approach:

- **Role Structure**: Uses peer-based specialists rather than hierarchical roles
- **Conversation Flow**: Focuses on natural multi-agent discussions rather than sequential research phases
- **Communication Style**: Implements @mention system for direct inter-agent communication
- **Paper Search**: Retrieves and analyzes papers from arXiv and bioRxiv

See `docs/AGENT_COLLABORATION.md` for a detailed comparison.

## Requirements

- Python 3.10+ (this workspace uses Python 3.13)
- Anthropic, Groq, Google Gemini, Zhipu BigModel and DashScope API credentials for the five-model configuration
- Dependencies:
  - anthropic>=1.0.0,<2.0.0
  - PyYAML>=6.0
  - PyPDF2>=3.0.0 (for PDF document processing)
  - requests>=2.25.1
  - feedparser>=6.0.0 (for research APIs)

## Advanced Usage


### Structured Discussions

Use the `/discuss` command to initiate a structured, multi-round discussion:

```
/discuss How might we develop more energy-efficient quantum computing architectures?
```

This starts a focused discussion where agents:
1. Provide initial perspectives
2. Build on each other's ideas
3. Work toward concrete outcomes

### Research Integration

Ask questions that require research:

```
What are the latest developments in large language model few-shot learning?
```

Agents will integrate information from arXiv and bioRxiv when appropriate.

### Paper Search and Reading

The system provides two ways to find and discuss scientific papers:

#### 1. Online Search via `/search`

```
/search protein folding --type arxiv --results 5
/search cancer immunotherapy --type biorxiv --months 6 --results 3
```

**Important Note on bioRxiv Search:**
The bioRxiv API does not provide full search functionality. Instead, it can only:
- List papers published within a specified time range (using the `--months` parameter)
- Return the most recent papers that include certain terms
- Results are deduplicated to show only the latest version of each paper

This means bioRxiv searches may not be as precise as arXiv searches. For specific papers or detailed searches, using the `/read_folder` command with local files may be more effective.

#### 2. Local Paper Reading via `/read_folder`

For cases where you have specific papers you want to discuss or when online search doesn't yield the needed results, you can use local PDF files:

```
/read_folder ~/papers/quantum_computing
```

This command will:
1. Scan the specified folder for PDF files
2. Display a list of found papers (based on filenames)
3. After typing 'continue', agents will read and discuss these papers

The `/read_folder` command provides a reliable alternative to online searches, especially when:
- You have specific papers you want the agents to analyze
- Online searches don't return the exact papers needed
- You need to discuss papers that might not be available through arXiv or bioRxiv

Both workflows follow the same pattern - after search or folder selection, type 'continue' to have agents read and discuss the papers.
