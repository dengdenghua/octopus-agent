# Tasks

- [x] Task 1: 从 package.json 移除 3 个未使用依赖
  - [x] SubTask 1.1: 从 dependencies 移除 `dompurify`
  - [x] SubTask 1.2: 从 devDependencies 移除 `@types/dompurify`
  - [x] SubTask 1.3: 从 devDependencies 移除 `tokenlens`

- [x] Task 2: 更新 lockfile
  - [x] SubTask 2.1: `pnpm install --no-frozen-lockfile` 更新 pnpm-lock.yaml

- [x] Task 3: 验证
  - [x] SubTask 3.1: `pnpm typecheck` 退出码 0
  - [x] SubTask 3.2: `pnpm lint` 退出码 0

- [x] Task 4: 提交 commit
  - [x] SubTask 4.1: commit message: `chore(frontend): remove unused deps (tokenlens, dompurify, @types/dompurify)`

# Task Dependencies

- Task 1 → Task 2 → Task 3 → Task 4
