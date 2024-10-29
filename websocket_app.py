# websocket_app.py
import asyncio
import websockets
import json
from chatbot import TwoAgentChatbot
from cache import SequenceCache
import sqlite3
from typing import Set, Optional
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class WebSocketServer:
    def __init__(self):
        logger.info("Initializing WebSocket Server and Chatbot...")
        self.sequence_cache = SequenceCache()
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.sequence_cache.set_update_callback(self.handle_db_update)
        self.sequence_cache.set_event_loop(asyncio.get_event_loop())
        self.chatbot = TwoAgentChatbot(sequence_cache=self.sequence_cache)

    async def handle_db_update(self, sequence_id: Optional[str], update_type: str):
        """Handle database updates based on type"""
        print(f"WebSocket handler received update - type: {update_type}, id: {sequence_id}")

        try:
            if update_type == 'update' and sequence_id:
                print(f">>> Attempting broadcast for {len(self.clients)} clients")
                print(f"Attempting to broadcast update for sequence: {sequence_id}")
                # Get the data in a separate thread to avoid blocking
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    self.executor,
                    self.sequence_cache.get_by_rnacentral_id,
                    sequence_id
                )
                
                if data:
                    message = json.dumps({
                        'type': 'db_update',
                        'sequence_id': sequence_id,
                        'data': data
                    })
                    
                    if self.clients:
                        await asyncio.gather(
                            *[client.send(message) for client in self.clients],
                            return_exceptions=True
                        )
                        print("Broadcast complete")
                    else:
                        print("No clients connected")
                else:
                    print(f"No data found for sequence: {sequence_id}")
                    
            elif update_type == 'clear':
                await self.broadcast_db_clear()
                await self.broadcast_full_state()
                
        except Exception as e:
            print(f"Error in handle_db_update: {str(e)}")
            print(f"Error type: {type(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise  # Re-raise to ensure the error is properly handled

    async def register(self, websocket):
        """Register new client and send initial state"""
        logger.info("New client connected")
        self.clients.add(websocket)
        await self.send_db_state(websocket)
        
    async def unregister(self, websocket):
        logger.info("Client disconnected")
        self.clients.remove(websocket)

    async def send_db_state(self, websocket):
        """Send complete DB state - used only for initial connection"""
        logger.info("Sending initial DB state to client")
        try:
            with sqlite3.connect(self.sequence_cache.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT sequence_id, sequence_data, num_locations, locations, 
                           friendly_name, rnacentral_link, trnascan_se_ss, sprinzl_pos, blocks_file
                    FROM sequences
                ''')
                rows = cursor.fetchall()
                
                db_state = [{
                    'sequence_id': row[0],
                    'sequence_data': json.loads(row[1]),
                    'num_locations': row[2],
                    'locations': json.loads(row[3]) if row[3] else [],
                    'friendly_name': row[4],
                    'rnacentral_link': row[5],
                    'tool_data': {
                        'trnascan_se_ss': json.loads(row[6]) if row[6] else None,
                        'sprinzl_pos': json.loads(row[7]) if row[7] else None,
                        'blocks_file': row[8] if row[8] else None
                    }
                } for row in rows]
                
                await websocket.send(json.dumps({
                    'type': 'db_state',
                    'data': db_state
                }))
                logger.info(f"Sent initial state with {len(db_state)} sequences")
        except Exception as e:
            logger.error(f"Error sending DB state: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")

    async def broadcast_full_state(self):
        """Broadcast full state to all clients - used only after clear"""
        logger.info("Broadcasting full state after clear")
        if not self.clients:
            return
        for client in self.clients:
            await self.send_db_state(client)

    async def broadcast_db_update(self, sequence_id: str):
        """Broadcast single sequence update to all clients"""
        logger.info(f"Broadcasting update for sequence: {sequence_id}")
        if not self.clients:
            logger.info("No clients connected, skipping broadcast")
            return
            
        try:
            data = self.sequence_cache.get_by_rnacentral_id(sequence_id)
            if data:
                message = json.dumps({
                    'type': 'db_update',
                    'sequence_id': sequence_id,
                    'data': data
                })
                await asyncio.gather(
                    *[client.send(message) for client in self.clients]
                )
                logger.info("Single sequence update broadcast complete")
            else:
                logger.warning(f"No data found for sequence: {sequence_id}")
        except Exception as e:
            logger.error(f"Error broadcasting update: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")

    async def broadcast_db_clear(self):
        """Notify all clients that DB has been cleared"""
        logger.info("Broadcasting DB clear")
        if not self.clients:
            return
            
        message = json.dumps({
            'type': 'db_clear'
        })
        await asyncio.gather(
            *[client.send(message) for client in self.clients]
        )

    async def handle_message(self, websocket):
        await self.register(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    user_input = data.get('message')
                    
                    if not user_input:
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': 'No message provided'
                        }))
                        continue

                    print(f"Processing query: {user_input}")
                    
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, 
                        self.chatbot.process_query,
                        user_input
                    )
                    
                    await websocket.send(json.dumps({
                        'type': 'response',
                        'message': response
                    }))
                    
                except Exception as e:
                    print(f"Error processing message: {str(e)}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': str(e)
                    }))
                    
        except websockets.exceptions.ConnectionClosed:
            print("Client connection closed")
        finally:
            await self.unregister(websocket)

    async def start(self, host='localhost', port=8765):
        print(f"Starting WebSocket server on ws://{host}:{port}")
        async with websockets.serve(self.handle_message, host, port):
            print("WebSocket server is running...")
            await asyncio.Future()

if __name__ == "__main__":
    server = WebSocketServer()
    asyncio.run(server.start())