import asyncio
import collections

# Grows by one entry per distinct (repo, pr_number) ever seen by this process
# and is never evicted -- acceptable for v1's traffic scale. Revisit with an
# LRU or TTL eviction if this ever becomes a real memory concern.
_locks: dict[tuple[str, int], asyncio.Lock] = collections.defaultdict(asyncio.Lock)


def get_lock(repo_full_name: str, pr_number: int) -> asyncio.Lock:
    return _locks[(repo_full_name, pr_number)]
