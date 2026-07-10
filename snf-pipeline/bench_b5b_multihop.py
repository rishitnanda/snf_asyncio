import asyncio


async def outer(res, timeout):
    await asyncio.wait_for(middle(res), timeout=timeout)


async def middle(res):
    await inner(res)


async def inner(res):
    try:
        await res.get()
    except asyncio.CancelledError:
        res.put_nowait("returned")