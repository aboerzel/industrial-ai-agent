[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')]
    [string]$ContainerName = 'ollama'
)

$ErrorActionPreference = 'Stop'
$Model = 'qwen3-embedding:0.6b'
$ModelFile = Join-Path $PSScriptRoot '../config/ollama/Modelfile.embedding-cpu'
$ContainerModelFile = '/tmp/industrial-embedding-cpu.Modelfile'

# Provision cached weights separately; this configuration step must not pull models.
& docker exec $ContainerName ollama show $Model --modelfile | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The cached local embedding model $Model must exist before configuration."
}

& docker cp $ModelFile "${ContainerName}:$ContainerModelFile"
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the embedding placement configuration.' }

& docker exec $ContainerName ollama create $Model -f $ContainerModelFile
if ($LASTEXITCODE -ne 0) { throw 'Could not configure CPU embedding placement.' }

$Parameters = & docker exec $ContainerName ollama show $Model --parameters
if ($LASTEXITCODE -ne 0 -or -not ($Parameters -match '^num_gpu\s+0\s*$')) {
    throw 'Ollama did not persist num_gpu=0 for the embedding model.'
}

# Bootstrap only: evict a previously loaded GPU instance before services start.
& docker exec $ContainerName ollama stop $Model
if ($LASTEXITCODE -ne 0) { throw 'Could not release the previous embedding instance.' }

Write-Output 'Local embeddings configured for CPU; chat model and assignments unchanged.'
