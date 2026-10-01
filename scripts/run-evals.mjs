#!/usr/bin/env node
/**
 * Run each skill's eval cases with and without the skill, grade them, and
 * write a benchmark.
 *
 * Origin: HaikeiLabs/skills (MIT). Changes for this repo:
 *   --skills-dir defaults to skills/claude (the canonical copy).
 *   --grader-model: separate model flag for the claude -p grader (was passing
 *   the harness --model to the grader, which claude rejected).
 *
 * For every eval in skills/<skill>/evals/evals.json this:
 *   1. creates two scratch projects: one with the skill installed in the
 *      harness's project skill directory, one without;
 *   2. runs the eval prompt headlessly in each with the chosen harness;
 *   3. asks a grader (always `claude -p`) to judge every expectation against
 *      the response, returning { text, passed, evidence } per expectation;
 *   4. writes response.md + grading.json per run and benchmark.{json,md}, in
 *      the skill-creator layout (eval-N/<config>/run-1/) so its eval viewer
 *      can open the results directly.
 *
 * Unlike the verify-* scripts this calls models, so it is not run in CI.
 * It needs the harness CLI on PATH and logged in.
 *
 * Usage:
 *   node scripts/run-evals.mjs [--skill NAME ...] [--harness claude|codex|opencode]
 *                              [--out DIR] [--no-baseline] [--jobs N] [--model M]
 *                              [--grader-model M] [--skills-dir DIR]
 *   node scripts/run-evals.mjs --grade-only DIR    # (re)grade existing DIR/<eval>/<config>/outputs/response.md
 *
 * --model: model for the harness under test (e.g. ray/deepseek-ai/DeepSeek-V4-Flash)
 * --grader-model: model for the claude -p grader (default: claude's default model)
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// Default to skills/claude (the canonical copy in this repo);
// override with --skills-dir.
let SKILLS = path.join(ROOT, 'skills', 'claude');

// Project-level skill directory each harness discovers from its cwd.
//
// Every harness is also isolated from user-level skills (~/.claude/skills,
// ~/.agents/skills, ...). Without that, a machine with the Haikei skills
// installed globally would load them in the "without skill" baseline too,
// and in "with skill" runs could load the installed copy instead of the one
// under test.
const HARNESSES = {
  claude: {
    skillDir: '.claude/skills',
    // Read-only: evals judge the written answer, and must never run kei,
    // log in, or touch credentials.
    // project,local: load the scratch project's .claude/skills but not ~/.claude.
    command: (prompt, model) => ['claude', ['-p', prompt, '--output-format', 'text',
      '--setting-sources', 'project,local',
      '--disallowedTools', 'Bash', 'Edit', 'Write', 'NotebookEdit', 'WebFetch', 'WebSearch',
      ...(model ? ['--model', model] : [])]],
  },
  codex: {
    skillDir: '.agents/skills',
    command: (prompt, model, cwd, outFile) => ['codex', ['exec', '--skip-git-repo-check',
      '--ephemeral', '-s', 'read-only', '-C', cwd, '-o', outFile,
      ...(model ? ['-m', model] : []), prompt]],
    readsOutputFile: true,
    // Codex reads user skills from $HOME/.agents/skills; give it an empty HOME
    // but keep CODEX_HOME so it stays logged in.
    env: () => ({ HOME: fs.mkdtempSync(path.join(os.tmpdir(), 'skill-eval-home-')),
      CODEX_HOME: process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex') }),
  },
  opencode: {
    skillDir: '.opencode/skills',
    command: (prompt, model, cwd) => ['opencode', ['run', '--dir', cwd,
      ...(model ? ['-m', model] : []), prompt]],
    // `opencode run` has no tool flags; deny the same tools via inline config.
    // Skip ~/.claude/skills and ~/.agents/skills; .opencode/skills still loads.
    env: () => ({
      OPENCODE_CONFIG_CONTENT: JSON.stringify({ permission: { bash: 'deny', edit: 'deny', webfetch: 'deny' } }),
      OPENCODE_DISABLE_CLAUDE_CODE_SKILLS: '1',
      OPENCODE_DISABLE_EXTERNAL_SKILLS: '1',
    }),
  },
};

function parseArgs(argv) {
  const opts = { skills: [], harness: 'claude', out: null, baseline: true, jobs: 4, model: null, graderModel: null, gradeOnly: null, skillsDir: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--skill') opts.skills.push(argv[++i]);
    else if (a === '--harness') opts.harness = argv[++i];
    else if (a === '--out') opts.out = argv[++i];
    else if (a === '--no-baseline') opts.baseline = false;
    else if (a === '--jobs') opts.jobs = Number(argv[++i]);
    else if (a === '--model') opts.model = argv[++i];
    else if (a === '--grader-model') opts.graderModel = argv[++i];
    else if (a === '--grade-only') opts.gradeOnly = argv[++i];
    else if (a === '--skills-dir') opts.skillsDir = argv[++i];
    else if (a === '-h' || a === '--help') {
      console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0]);
      process.exit(0);
    } else throw new Error(`unknown argument ${a}`);
  }
  if (!HARNESSES[opts.harness]) throw new Error(`--harness must be one of ${Object.keys(HARNESSES).join(', ')}`);
  return opts;
}

function run(cmd, args, cwd, timeoutMs = 600_000, env = {}) {
  return new Promise((resolve) => {
    const started = Date.now();
    const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    const timer = setTimeout(() => child.kill('SIGTERM'), timeoutMs);
    child.on('error', (err) => { clearTimeout(timer); resolve({ code: -1, stdout, stderr: String(err), ms: Date.now() - started }); });
    child.on('close', (code) => { clearTimeout(timer); resolve({ code, stdout, stderr, ms: Date.now() - started }); });
  });
}

function scratchProject(skill, withSkill, harness) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `skill-eval-${skill}-`));
  if (withSkill) {
    const dest = path.join(dir, HARNESSES[harness].skillDir);
    fs.mkdirSync(dest, { recursive: true });
    fs.cpSync(path.join(SKILLS, skill), path.join(dest, skill), { recursive: true });
  }
  return dir;
}

async function answer(skill, prompt, withSkill, opts, runDir) {
  const cwd = scratchProject(skill, withSkill, opts.harness);
  const outFile = path.join(cwd, 'last-message.md');
  const [cmd, args] = HARNESSES[opts.harness].command(prompt, opts.model, cwd, outFile);
  const res = await run(cmd, args, cwd, 600_000, HARNESSES[opts.harness].env?.() ?? {});
  let response = res.stdout;
  if (HARNESSES[opts.harness].readsOutputFile && fs.existsSync(outFile)) {
    response = fs.readFileSync(outFile, 'utf8');
  }
  fs.mkdirSync(path.join(runDir, 'outputs'), { recursive: true });
  fs.writeFileSync(path.join(runDir, 'outputs', 'response.md'), response);
  fs.writeFileSync(path.join(runDir, 'timing.json'), JSON.stringify({
    total_duration_seconds: res.ms / 1000, exit_code: res.code,
  }, null, 2));
  if (res.code !== 0) fs.writeFileSync(path.join(runDir, 'stderr.txt'), res.stderr);
  fs.rmSync(cwd, { recursive: true, force: true });
  // A harness failure (auth, usage limit, crash) is not a skill failure:
  // report it instead of grading an empty answer.
  if (res.code !== 0 || !response.trim()) {
    const reason = res.stderr.trim().split('\n').filter(Boolean).pop() ?? `exit ${res.code}`;
    return { error: reason };
  }
  return { response };
}

async function grade(prompt, expectations, response, runDir, graderModel) {
  const graderPrompt = `You are grading an AI assistant's answer against expectations.
Judge each expectation strictly from the answer text. An expectation passes only
if the answer clearly satisfies it; quote the evidence.

Return ONLY a JSON object, no prose, of the form:
{"expectations":[{"text":"<expectation verbatim>","passed":true|false,"evidence":"<short quote or reason>"}]}

User prompt:
<<<
${prompt}
>>>

Expectations:
${expectations.map((e, i) => `${i + 1}. ${e}`).join('\n')}

Answer to grade:
<<<
${response}
>>>`;
  let parsed;
  // Retry once: the grader occasionally wraps or truncates its JSON.
  for (let attempt = 0; attempt < 2 && !parsed; attempt++) {
    const res = await run('claude', ['-p', graderPrompt, '--output-format', 'text',
      '--disallowedTools', 'Bash', 'Edit', 'Write', 'Read', 'WebFetch', 'WebSearch',
      ...(graderModel ? ['--model', graderModel] : [])], os.tmpdir());
    try {
      const candidate = JSON.parse(res.stdout.slice(res.stdout.indexOf('{'), res.stdout.lastIndexOf('}') + 1));
      if (Array.isArray(candidate.expectations) && candidate.expectations.length === expectations.length) parsed = candidate;
    } catch { /* retry */ }
  }
  parsed ??= { expectations: expectations.map((text) => ({ text, passed: false, evidence: 'grader output was not valid JSON' })) };
  const passed = parsed.expectations.filter((e) => e.passed).length;
  const grading = {
    expectations: parsed.expectations,
    summary: { passed, failed: parsed.expectations.length - passed, total: parsed.expectations.length,
      pass_rate: parsed.expectations.length ? passed / parsed.expectations.length : 0 },
  };
  fs.writeFileSync(path.join(runDir, 'grading.json'), JSON.stringify(grading, null, 2));
  return grading;
}

async function pool(tasks, jobs) {
  const results = [];
  let next = 0;
  await Promise.all(Array.from({ length: Math.max(1, jobs) }, async () => {
    while (next < tasks.length) {
      const i = next++;
      results[i] = await tasks[i]();
    }
  }));
  return results;
}

// Grade responses that already exist, e.g. from a run driven by subagents or
// another harness: DIR/<eval>/eval_metadata.json + DIR/<eval>/<config>/outputs/response.md.
async function gradeExisting(dir, opts) {
  const tasks = [];
  for (const evalName of fs.readdirSync(dir)) {
    const metaPath = path.join(dir, evalName, 'eval_metadata.json');
    if (!fs.existsSync(metaPath)) continue;
    const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
    for (const config of fs.readdirSync(path.join(dir, evalName))) {
      const configDir = path.join(dir, evalName, config);
      if (!fs.statSync(configDir).isDirectory()) continue;
      const runDirs = fs.readdirSync(configDir).filter((r) => r.startsWith('run-')).map((r) => path.join(configDir, r));
      for (const runDir of runDirs.length ? runDirs : [configDir]) {
        const responsePath = path.join(runDir, 'outputs', 'response.md');
        if (!fs.existsSync(responsePath)) continue;
        tasks.push(async () => {
          process.stderr.write(`grading ${evalName} ${config}\n`);
          const g = await grade(meta.prompt, meta.assertions, fs.readFileSync(responsePath, 'utf8'), runDir, opts.graderModel);
          return { skill: meta.skill ?? evalName, id: meta.eval_id, config, ...g.summary };
        });
      }
    }
  }
  return pool(tasks, opts.jobs);
}

function report(results, out, opts) {
  const errors = results.filter((r) => r.error);
  const bySkill = {};
  for (const r of results) {
    if (r.error) continue;
    const s = (bySkill[r.skill] ??= {});
    const c = (s[r.config] ??= { passed: 0, total: 0 });
    c.passed += r.passed;
    c.total += r.total;
  }
  const benchmark = { harness: opts.harness, model: opts.model, created_at: new Date().toISOString(), results, by_skill: bySkill };
  fs.writeFileSync(path.join(out, 'skill-benchmark.json'), JSON.stringify(benchmark, null, 2));

  const pct = (c) => (c && c.total ? `${Math.round((100 * c.passed) / c.total)}% (${c.passed}/${c.total})` : '—');
  const lines = [`# Skill eval benchmark (${opts.harness})`, '', '| Skill | With skill | Without skill |', '| --- | --- | --- |'];
  for (const [skill, c] of Object.entries(bySkill)) lines.push(`| ${skill} | ${pct(c.with_skill)} | ${pct(c.without_skill)} |`);
  fs.writeFileSync(path.join(out, 'skill-benchmark.md'), `${lines.join('\n')}\n`);
  console.log(lines.join('\n'));
  console.log(`\nresults: ${out}`);

  if (errors.length) {
    console.error(`\n${errors.length} run(s) did not complete (not graded):`);
    for (const e of errors) console.error(`  ${e.skill} #${e.id} ${e.config}: ${e.error}`);
    process.exit(2);
  }

  // Non-zero when a skill fails more expectations than it passes, so the
  // script can gate a manual release check.
  const regressions = Object.entries(bySkill).filter(([, c]) => c.with_skill && c.with_skill.passed * 2 < c.with_skill.total);
  if (regressions.length) {
    console.error(`below 50% with the skill: ${regressions.map(([s]) => s).join(', ')}`);
    process.exit(1);
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.skillsDir) SKILLS = path.resolve(opts.skillsDir);
  if (opts.gradeOnly) {
    const dir = path.resolve(opts.gradeOnly);
    report(await gradeExisting(dir, opts), dir, opts);
    return;
  }
  const skills = opts.skills.length
    ? opts.skills
    : fs.readdirSync(SKILLS).filter((d) => fs.existsSync(path.join(SKILLS, d, 'evals', 'evals.json')));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const out = path.resolve(opts.out ?? path.join(ROOT, 'evals-out', `${opts.harness}-${stamp}`));
  const configs = opts.baseline ? ['with_skill', 'without_skill'] : ['with_skill'];

  const tasks = [];
  let n = 0;
  for (const skill of skills) {
    const { evals } = JSON.parse(fs.readFileSync(path.join(SKILLS, skill, 'evals', 'evals.json'), 'utf8'));
    for (const ev of evals) {
      const evalDir = path.join(out, `eval-${++n}-${skill}-${ev.id}`);
      fs.mkdirSync(evalDir, { recursive: true });
      fs.writeFileSync(path.join(evalDir, 'eval_metadata.json'), JSON.stringify({
        eval_id: ev.id, eval_name: `${skill}-eval-${ev.id}`, skill, prompt: ev.prompt, assertions: ev.expectations,
      }, null, 2));
      for (const config of configs) {
        tasks.push(async () => {
          const runDir = path.join(evalDir, config, 'run-1');
          process.stderr.write(`running ${skill} #${ev.id} ${config}\n`);
          const { response, error } = await answer(skill, ev.prompt, config === 'with_skill', opts, runDir);
          if (error) return { skill, id: ev.id, config, passed: 0, failed: 0, total: 0, error };
          const grading = await grade(ev.prompt, ev.expectations, response, runDir, opts.graderModel);
          return { skill, id: ev.id, config, ...grading.summary };
        });
      }
    }
  }

  report(await pool(tasks, opts.jobs), out, opts);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(2);
});
