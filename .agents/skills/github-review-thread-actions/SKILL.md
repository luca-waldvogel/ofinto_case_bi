---
name: github-review-thread-actions
description: Reply to and resolve individual GitHub pull-request review threads with GitHub CLI GraphQL mutations after their feedback has been addressed.
---

Use a review thread node ID obtained from GitHub. Every reply body must start exactly with
`RESOLVER AGENT:`. Reply with:

```bash
gh api graphql -f query='mutation($threadId:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){comment{url}}}' -f threadId="$thread_id" -f body="$reply"
```

Resolve with:

```bash
gh api graphql -f query='mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id isResolved}}}' -f threadId="$thread_id"
```

Resolve only after the requested change is complete and proportionate checks pass. Reply first,
state briefly what was changed, then resolve and verify `isResolved` is true in the response. If a
thread only asks a question, answer it and leave the thread unresolved. Never resolve a partially
addressed or blocked request, and never retry a mutation after an ambiguous failure without first
reading the thread state.
