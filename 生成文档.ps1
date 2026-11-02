param(
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw '未找到 Python。请通过 -Python 指定已安装依赖的解释器路径。'
}
$builder = Join-Path $PSScriptRoot '源文件\build.py'
& $Python $builder --config $Config
if ($LASTEXITCODE -ne 0) {
    throw 'HTML 生成未完成，请根据上方提示修正；不要手工拼装 HTML。'
}
