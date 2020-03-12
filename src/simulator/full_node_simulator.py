from secrets import token_bytes

from src.full_node.full_node import FullNode
from typing import AsyncGenerator, List, Dict, Optional
from src.full_node.blockchain import Blockchain
from src.full_node.store import FullNodeStore
from src.protocols import (
    full_node_protocol,
    wallet_protocol,
)
from src.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from src.util.bundle_tools import best_solution_program
from src.full_node.mempool_manager import MempoolManager
from src.server.outbound_message import OutboundMessage
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.types.hashable.spend_bundle import SpendBundle
from src.types.header import Header
from src.full_node.coin_store import CoinStore
from src.util.api_decorators import api_request
from tests.block_tools import BlockTools

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]

bt = BlockTools()


class FullNodeSimulator(FullNode):
    def __init__(
        self,
        store: FullNodeStore,
        blockchain: Blockchain,
        config: Dict,
        mempool_manager: MempoolManager,
        coin_store: CoinStore,
        name: str = None,
        override_constants=None,
    ):
        super().__init__(
            store,
            blockchain,
            config,
            mempool_manager,
            coin_store,
            name,
            override_constants,
        )

    def _set_server(self, server: ChiaServer):
        super()._set_server(server)

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """
        async for msg in super()._on_connect():
            yield msg

    @api_request
    async def respond_block(
        self, respond_block: full_node_protocol.RespondBlock
    ) -> OutboundMessageGenerator:
        async for msg in super().respond_block(respond_block):
            yield msg

    # WALLET PROTOCOL
    @api_request
    async def send_transaction(
        self, tx: wallet_protocol.SendTransaction
    ) -> OutboundMessageGenerator:
        async for msg in super().send_transaction(tx):
            yield msg

    @api_request
    async def request_all_proof_hashes(
        self, request: wallet_protocol.RequestAllProofHashes
    ) -> OutboundMessageGenerator:
        async for msg in super().request_all_proof_hashes(request):
            yield msg

    @api_request
    async def request_all_header_hashes_after(
        self, request: wallet_protocol.RequestAllHeaderHashesAfter
    ) -> OutboundMessageGenerator:
        async for msg in super().request_all_header_hashes_after(request):
            yield msg

    @api_request
    async def request_header(
        self, request: wallet_protocol.RequestHeader
    ) -> OutboundMessageGenerator:
        async for msg in super().request_header(request):
            yield msg

    @api_request
    async def request_removals(
        self, request: wallet_protocol.RequestRemovals
    ) -> OutboundMessageGenerator:
        async for msg in super().request_removals(request):
            yield msg

    @api_request
    async def request_additions(
        self, request: wallet_protocol.RequestAdditions
    ) -> OutboundMessageGenerator:
        async for msg in super().request_additions(request):
            yield msg

    # WALLET LOCAL TEST PROTOCOL
    def get_tip(self):
        tips = self.blockchain.tips
        top = tips[0]

        for tip in tips:
            if tip.height > top.height:
                top = tip

        return top

    async def get_current_blocks(self, tip: Header) -> List[FullBlock]:

        current_blocks: List[FullBlock] = []
        tip_hash = tip.header_hash

        while True:
            if tip_hash == self.blockchain.genesis.header_hash:
                current_blocks.append(self.blockchain.genesis)
                break
            full = await self.store.get_block(tip_hash)
            assert full is not None
            current_blocks.append(full)
            tip_hash = full.prev_header_hash

        current_blocks.reverse()
        return current_blocks

    @api_request
    async def farm_new_block(self, request: FarmNewBlockProtocol):
        self.log.info("Farming new block!")
        top_tip = self.get_tip()

        current_block = await self.get_current_blocks(top_tip)
        bundle: Optional[
            SpendBundle
        ] = await self.mempool_manager.create_bundle_for_tip(top_tip)
        assert bundle is not None
        dict_h = {}

        if bundle:
            program = best_solution_program(bundle)
            dict_h[top_tip.height + 1] = (program, bundle.aggregated_signature)

        more_blocks = bt.get_consecutive_blocks(
            self.constants,
            1,
            current_block,
            10,
            reward_puzzlehash=request.puzzle_hash,
            transaction_data_at_height=dict_h,
        )
        new_lca = more_blocks[-1]

        assert self.server is not None
        async for msg in self.respond_block(full_node_protocol.RespondBlock(new_lca)):
            self.server.push_message(msg)

    @api_request
    async def reorg_from_index_to_new_index(self, request: ReorgProtocol):
        new_index = request.new_index
        old_index = request.old_index
        coinbase_ph = request.puzzle_hash
        top_tip = self.get_tip()

        current_blocks = await self.get_current_blocks(top_tip)
        block_count = new_index - old_index

        more_blocks = bt.get_consecutive_blocks(
            self.constants,
            block_count,
            current_blocks[:old_index],
            10,
            seed=token_bytes(),
            reward_puzzlehash=coinbase_ph,
            transaction_data_at_height={},
        )
        assert self.server is not None
        for block in more_blocks:
            async for msg in self.respond_block(full_node_protocol.RespondBlock(block)):
                self.server.push_message(msg)
                self.log.info(f"New message: {msg}")
