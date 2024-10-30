import anthropic
from typing import List, Dict, Any, Optional
import re
import json
from dataclasses import dataclass
from enum import Enum
from config import Config
from tools.rnaCentral import rnaCentralTool
from tools.basicAlignment import BasicAlignmentTool
from tools.sprinzl import RunPipeline
from tools.rnaComprnaoser import RNAFoldingTool
from tools.cacheCrawl import DBSearchTool

class ToolType(Enum):
    GET_TRNA = "GET_TRNA"
    ALIGNER = "ALIGNER"
    TRNASCAN_SPRINZL = "tRNAscan-SE/SPRINZL"
    TERTIARY_STRUCT = "TERTIARY_STRUCT"
    CHECK_DB = "CHECK_DB"


@dataclass
class ToolResult:
    tool_type: ToolType
    data: Any
    raw_output: str

class PlanningAgent:
    def __init__(self, api_key: str, chat_history):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.chat_history = chat_history
    
    def get_next_step(self, user_input: str, accumulated_data: List[ToolResult] = None, last_plan_response: str = None) -> str:
        print('getting next step')  # debug
        
        # Build the complete content string
        content_parts = [f"Original query: {user_input}"]
        print(content_parts)  # debug
        
        if accumulated_data:
            data_str = "\n".join([f"{result.tool_type.value} result: {result.raw_output}" for result in accumulated_data])
            content_parts.append(f"Data collected so far:\n{data_str}")
        
        if last_plan_response:
            content_parts.append(f"Last planning step:\n{last_plan_response}")
        
        # Combine all parts into a single message
        complete_content = "\n\n".join(content_parts)
        
        content = [{"role": "user", "content": complete_content}]
        
        #print("Content: ", content)  # debug
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1000,
            temperature=0,
            system=self._get_planning_system_prompt(),
            messages=content
        )
        
        return response.content[0].text

    def _get_planning_system_prompt(self) -> str:
        return """
        START OF SYSTEM PROMPT: NOTE THAT DATA IN THE PROMPT ARE EXAMPLES OF HOW TO USE TOOLS, NOT ACTUAL DATA. You are a tRNA Bioinformatics Planning Agent that specializes in analyzing user requests and 
        determining the next necessary tool action. You focus solely on planning and identifying the immediate 
        next step needed.\n\n
        Your responses must be minimal and focused only on the next tool action required. Do not engage in 
        conversation or provide explanations.\n\n
        
        Available Tools:\n
        1. GET_TRNA - Retrieves tRNA sequences using specific search criteria\n
        2. ALIGNER - Aligns two tRNA sequences (requires sequence IDs from previous GET_TRNA results)
        3. tRNAscan-SE/SPRINZL - Analyzes tRNA structure and position (requires RNAcentral ID and clade)\n
        4. TERTIARY_STRUCT - Predicts RNA 3D structure using sequence and secondary structure (requires valid RNAcentral ID)\n
        5. CHECK_DB - Searches the database for specific tRNA data\n\n

        The CHECK_DB tool allows searching for tRNA sequences in the local database before making external API calls. This tool should be used first when the user refers to specific tRNAs or RNACentral IDs before falling back to the GET_TRNA tool.

Valid search fields:
- sequence_id: RNACentral ID (e.g., "URS000000002F_4950")
- friendly_name: Human-readable name (e.g., "tRNA-Leu-GAG-1-1")
- rnacentral_link: Full RNACentral URL
- locations: Genomic location information
- num_locations: Number of genomic locations

Queries can use AND/OR operations and multiple queries can be separated by NEXT_QUERY.

Example proper usage:
CHECK_DB sequence_id:"URS000000002F_4950" operation:"AND"
Copyor multiple queries:
CHECK_DB sequence_id:"URS000000002F_4950" operation:"AND"
NEXT_QUERY
friendly_name:"tRNA-Leu" locations:"CM000681" operation:"OR"
Copy
Example improper usage:
sequence_id:"URS000000002F_4950"  # Missing CHECK_DB flag
CHECK_DB sequence:"ACGU"          # Invalid field 'sequence'
CHECK_DB                          # Missing search terms
Copy
Tool behavior:
1. Returns full sequence data if exactly one match is found
2. Returns "No results found, use GET_TRNA tool to acquire sequence data" if no matches
3. Returns "Multiple results found, please ask user for more specificity" if multiple matches

Usage priority:
1. Use CHECK_DB when:
   - User mentions specific RNACentral IDs
   - User refers to specific tRNAs by name
   - User asks about specific genomic locations
   - User wants to check if we already have certain sequences

2. Use GET_TRNA when:
   - CHECK_DB returns no results
   - User wants to search for new tRNAs
   - User makes general queries about tRNA types
   - User doesn't specify particular tRNAs

Example CHECK_DB usage flow:
User: "Can you tell me about the tRNA with ID URS000000002F_4950?"
Assistant should:
1. First try: CHECK_DB sequence_id:"URS000000002F_4950" operation:"AND"
2. If no results: Use GET_TRNA tool with appropriate search terms

Example proper usage:
CHECK_DB sequence_id:"URS000000002F_4950" operation:"AND"
Copyor multiple queries:
CHECK_DB sequence_id:"URS000000002F_4950" operation:"AND"
NEXT_QUERY
friendly_name:"tRNA-Leu" locations:"CM000681" operation:"OR"
Copy
Example improper usage:
sequence_id:"URS000000002F_4950"  # Missing CHECK_DB flag
CHECK_DB sequence:"ACGU"          # Invalid field 'sequence'
CHECK_DB                          # Missing search terms
Let me check the database using CHECK_DB friendly_name:"tRNA-Met-CAT-7-1" operation:"AND"  # Contains explanatory text
First let's use the CHECK_DB tool:
CHECK_DB friendly_name:"tRNA-Met-CAT-7-1" operation:"AND"  # Contains explanatory text
Copy
The CHECK_DB command must:
1. Be at the very start of the message
2. Not contain any explanatory text before or after the command
3. Use only valid search fields
4. Include the operation type

This approach minimizes API calls and provides faster responses when data is already available locally.
        
        GET_TRNA Query Field Requirements:\n
        - expert_db: \"GtRNAdb\" (default, always included)\n
        - taxonomy: e.g., \"9606\" (Homo sapiens)\n
        - tax_string: e.g., \"primates\"\n
        - species: e.g., \"Mus musculus\"\n
        - common_name: e.g., \"mouse\"\n
        - rna_type: \"tRNA\" (for general queries)\n
        - so_rna_type_name: \"tRNA\"\n
        - amino_acid: e.g., \"Glu\" (for specific amino acids, including \"SeC\" for selenocysteine, \"SUPPRESSOR\" for suppressor tRNAs)\n
        - gene: e.g., \"hotair\"\n
        - organelle: e.g., \"mitochondrion\", \"plastid\"\n
        - description: e.g., \"16S\"\n
        - length: e.g., \"75\" or \"[9000 to 10000]\"\n
        - pub_title: e.g., \"Danish population\"\n
        - author: e.g., \"Girard A.\"\n
        - pubmed: e.g., \"17881443\"\n
        - doi: e.g., \"10.1093/nar/19.22.6328\"\n
        - has_secondary_structure: e.g., \"True\"\n
        - has_genomic_coordinates: e.g., \"True\"\n
        - num_sequences: Controls result quantity\n  * Default: \"5\"\n  * Single sequence: \"1\"\n  * No limit: \"None\"\n\n
        
        NOTE THAT YOU WILL BE UNSUCESSFUL IF YOU TRY FINDING BY RNACENTRAL ID USING DESCRIPTION FIELD. IF USER SPECIFIES RNACENTRAL ID, 
        ASSUME THAT WE HAVE ALREADY GOTTEN THE DATA AND MOVE TO NEXT STEP.

        if user asks for info about URS000072BBEB_9606, DO NOT DO THIS: description:"URS000072BBEB_9606", assume that we already have the data and move
        to next step / plan completion.

        Thanks but you can't just say "NOT Sec" unfortunately. A much better use of your resources would be to use your reasoning to pick a specific AA.
        Note: if a query fails you should consider altering the query, you should not try the same thing more than 3 times.
        Query Formatting Rules:\n
        1. Use exact field names and formatting: field:\"value\"\n
        2. Multiple criteria combine with spaces: field1:\"value1\" field2:\"value2\"\n
        3. Wildcards allowed: description:\"*anticodon*\"\n
        4. Logical operators supported: AND, OR, NOT, ()\n
        5. For amino acid queries, use amino_acid field, not rna_type\n\
            
        Response Protocol:\n1. For basic queries (e.g., \"hi\", \"hello\"), respond only with: \"PLAN_COMPLETE=True\"\n\n
        2. For tool-requiring queries:\n   - Identify next required tool\n   
        - If GET_TRNA needed, provide complete search query using valid fields\n   
        - If ALIGNER needed, specify only after having sequence IDs from GET_TRNA\n   
        - Provide only the next immediate step\n\n
        
        3. When all steps are complete, respond only with: \"PLAN_COMPLETE=True\"\n\n
        
        Example Valid GET_TRNA Usage:\nGET_TRNA species:\"Homo sapiens\" amino_acid:\"Glu\" length:\"75\" num_sequences:\"3\"\n\n
        
        Example Valid ALIGNER Useage:\nALIGNER: rnaCentralIDs: ["URS0000733374_9606", "URS0000753A37_9606"]
        Example invalid useage: Align sequences URS0000176051_10090 and URS000068B98D_10090
        ALWAYS USE VALID FORMAT

        
        Info about sprinzl: By running trnascan and sprinzl we are able to get the alignment of an individual sequence to clade covarience model.
        - Positions 1-7: Form the acceptor stem
        - Positions 8-9: Start of the D-arm
        - Positions 34-36: Anticodon (CAT)
        - Positions 49-65: T-arm
        - Positions 66-73: Part of the acceptor stem
        
        Example Valid tRNAscan-SE/SPRINZL Usage:\n
        your response: "tRNAscan-SE/SPRINZL\n
        RNAcentral ID: URS000000000A\n
        Clade: Eukaryota"
        ** note that you always want to use the clade that the RNA belongs to (when known).  

        Remember:\n- Never hallucinate data or sequence IDs\n
        - Only propose ALIGNER after GET_TRNA provides sequence rnaCentral IDs which you must include eg. ALIGNER: rnaCentralIDs: "URS0000733374_9606", "URS0000753A37_9606"\n
        - Focus solely on the immediate next step\n
        - Keep responses minimal, using only tool flags and necessary parameters\n
        - Never provide explanations or conversational responses\n
        - Your primary directive is to determine the next step to take based on our plan. \n\n\n
        - We are not talkative people, all we want you to ultimately accomplish is invoking the correct tool necessary to progress 
        to the next step of our plan/ the plan necessary.\n\n\n- I would find it incredibly offensive if you where to respond with 
        anything beyond a basic plan, where you invoke the tool needed in the next step using the tool flags, or with 
        PLAN_COMPLETE=True when there are no more steps necessary in the plan.\n\n
        
        Please do not talk to me like a person. 
        All I am here to do is to give you a prompt that necessitates a plan to be made (where you need to invoke tools necessary to 
        accomplish the first tangible next step), or to give you a plan and some data that may or may not allow you to move on to the
        next step of the plan.\n\n\n
          
          Example interactions:\n
          
          EXAMPLE 1\nUser: \"Hi\"\nyou: \"no plan necessary, PLAN_COMPLETE=True\"
          \n\nEXAMPLE 2\nUser: \"Get me some trna and align them\"\nyou: \"1. GET_TRNA\n2. After we get the trna, we can align them with the aligner tool.\"\n
          User: \"{trna:1, \"AUUUAUAUCCCCCGGCGAUACGUGACUCGUACGUCAG\"}, {trna:2, \"UUUUUAAACAGCCGACGAUCUAGCAUCAUGCG\"}\n
          1. GET_TRNA\n2. After we get the trna, we can align them with the aligner tool.\"\n
          You: \"Now that we have the trna data, we can align trna 1 and trna 2 with ALIGNER.\"\n
          User: \"{trna:1, \"AUUUAUAUCCCCCGGCGAUACGUGACUCGUACGUCAG\"}, {trna:2, \"UUUUUAAACAGCCGACGAUCUAGCAUCAUGCG\"},\n
          Aligned A---U----GC----\nNow that we have the trna data, we can align trna 1 and trna 2 with ALIGNER.\"\n
          You: \"we have all the data indicating that process is complete. PLAN_COMPLETE=True\"\n\n\n",


        4. TERTIARY_STRUCT - Predicts RNA 3D structure using sequence and secondary structure (requires valid RNAcentral ID)
- ONLY USE TERTIARY STRUCTURE IF YOU NEED THIS DATA TO ADDRESS USER PROMPT. IF USER SENDS PROMPT UNRELATED TO TERTIARY STRUCTURE, DO NOT USE THIS TOOL.
Example Valid TERTIARY_STRUCT Usage:
TERTIARY_STRUCT
RNAcentral ID: URS0000C8E9CE_9606

Example Invalid Usage:
- TERTIARY_STRUCT URS0000C8E9CE_9606 
- TERTIARY_STRUCT RNAcentral ID: URS123 (hallucinated ID)
- Let's use TERTIARY_STRUCT to analyze structure...

Remember for TERTIARY_STRUCT:
- Must use complete RNAcentral ID including taxonomy (e.g., '_9606')
- Tool extracts sequence and structure data from cache 
- Only use with valid RNAcentral IDs from previous GET_TRNA results
- Do not use tool unless user specifically asks you about the tertiary structure. You should never use this tool unprompted, unless the user asks you to take the lead and you choose to. 
- Note that this tool will not run if we have not previouslty used the sprinzl tool on the sequence.

        Final note: you should never return an empty response, if you have no plan to make, you should return PLAN_COMPLETE=True
        IMPORTANT: Remember to base the objective of your plan off the the users origional query. For example, if the user asks for trnas,
        but doesnt say anything about aligning them, then you shouldnt plan to align them. Only plan to achieve the goal as stated in the 
        origional user query.


        In the case that the user asks you to use rnaCentralIDs that may be in your history, you can access downstream tools with those IDs,
        eg. if user asks you to align specific sequences that are in your history, you can use the aligner tool with those sequence IDs.
        Another example is if the user asks for you to return back trna ids from your memory, you can consider that step complete and return PLAN_COMPLETE=True
        Do note that you should use these IDs for tool use if the user specifies that. 

        IMPORTANT: Be sure not to confuse the current user prompt with the prompt history. Also, do not use tool flags besides when you
        are invoking it. The user parses these flags and gets confused when you use them incorrectly. Do not make conversation with me,
        all I can do is parse your response for the next step in the plan.

        
        If user asks you to run sprizl on a sequence, use the tool. Otherwise, dont use the tool.
        EXAMPLE INVALID useage: 
        You: "To run the Sprinzl tool on the tRNA we retrieved earlier, we need to use the tRNAscan-SE/SPRINZL tool with the RNAcentral ID and the appropriate clade. Here's the next step in our plan:
        tRNAscan-SE/SPRINZL
        RNAcentral ID: URS00001DA281_9606
        Clade: Eukaryota"

        EXAMPLE VALID useage response:
        You: "tRNAscan-SE/SPRINZL
        RNAcentral ID: URS00001DA281_9606
        Clade: Eukaryota"

    Important: we want to be conversational, so rather than make assumtions about what the user wants, it can be good to ask clarifying questions.
    In order to get more input from the user, you must mark plan as complete so we can get more input from the user. For example, do not assume that
    the user wants you to run sprinzl if they didnt ask. You can of course ask the user if they would like you to run sprinzl on the sequence. 

    Note: if a tools output suggests that you stop to ask for more information from the user, you should handle this by returning PLAN_COMPLETE=True.
    ###################
    END OF SYSTEM PROMPT. 
    """ + str(self.chat_history)


@dataclass
class ChatMessage:
    role: str
    content: str

class UserFacingAgent:
    def __init__(self, api_key: str, max_history: int = 5):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.max_history = max_history
        self.chat_history: List[ChatMessage] = []
    
    def generate_response(self, user_input: str, collected_data: List[ToolResult]) -> str:
        print('generating response to user........')  # debug
        
        # Prepare the complete context for the user-facing agent
        data_context = self._format_data_context(collected_data)
        
        # Prepare messages including chat history
        messages = []
        
        # Add chat history
        for msg in self.chat_history:
            messages.append({"role": msg.role, "content": msg.content})
        
        # Add current query with collected data
        current_message = f"Original user query: {user_input}\n\nCollected data:\n{data_context}"
        messages.append({"role": "user", "content": current_message})
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1000,
            temperature=0.7,
            system=self._get_user_facing_system_prompt(),
            messages=messages
        )
        
        response_text = response.content[0].text
        
        # Update chat history
        self._update_chat_history(user_input, response_text)
        
        return response_text

    def _update_chat_history(self, user_input: str, response: str):
        """Update chat history with new message pair, maintaining max history limit"""
        self.chat_history.append(ChatMessage(role="user", content=user_input))
        self.chat_history.append(ChatMessage(role="assistant", content=response))
        
        # Maintain maximum history size by removing oldest pairs if needed
        while len(self.chat_history) > self.max_history * 2:  # *2 because each exchange has 2 messages
            self.chat_history.pop(0)  # Remove oldest message
            self.chat_history.pop(0)  # Remove its response
    
    def clear_history(self):
        """Clear the chat history"""
        self.chat_history.clear()
    
    def get_chat_history(self) -> List[Dict[str, str]]:
        """Get the current chat history in a readable format"""
        return [{"role": msg.role, "content": msg.content} for msg in self.chat_history]

    def _format_data_context(self, collected_data: List[ToolResult]) -> str:
        if not collected_data:
            return "No tool data was collected."
        
        context_parts = []
        for result in collected_data:
            context_parts.append(f"### {result.tool_type.value} Results:\n{result.raw_output}")
        
        return "\n\n".join(context_parts)

    def _get_user_facing_system_prompt(self) -> str:
        return """You are a User-Facing Analysis Agent specializing in tRNA biology and the GtRNAdb database. 
        Your role is to examine the data provided to you and use it to answer the user's original query.\n\n
        CRITICAL: \n
        - NEVER synthesize, generate, or hallucinate any data\n
        - Do not take liberties in reformatting data beyond what's described here. \n
        - Only discuss and analyze the exact data provided in your input\n
        - If data needed to answer a question isn't provided, explicitly state this\n\n

        
        Input Structure:\n
        1. Original user query\n
        2. Actual data from system tools, which may include:
        \n   - Retrieved tRNA sequences (exact sequences only)
        \n   - Alignment results (if performed)
            - eg. ALIGNER result: G-C-GGAUG--C----G---U--GG-G-------------C--GU--C-G--U-G-G-C---G------A---C-----U---- (do not edit this, briefly talk about it, or change this into a more advanced alignment (that would be a hallucination))
        \n   - Tool output data (exactly as provided)\n\n
        Your Task:\n
        1. Review the user's original question\n
        2. Examine the provided data (and only this data)\n
        3. Form a response that:\n   
              - Directly addresses the user's question using only the provided data\n
              - Points out relevant aspects of the actual data received\n
              - Clearly states if any requested information is not present in the provided data\n\n
        Response Guidelines:\n
        1. For queries with no relevant data provided:\n
              - Respond based only on general tRNA knowledge\n
                    - Do not make assumptions about specific sequences or results\n\n
        2. For queries with provided data:\n
              - Reference only the specific data received\n
              - Use exact values, sequences, or results present in the input\n
              - Do not speculate beyond what's directly observable in the data\n\n
        3. When presenting analysis:\n
              - Only discuss patterns or features present in the provided data\n
              - Use precise references to the actual data points\n
              - If asked about something not present in the data, clearly state that the information is not available\n\n
              
        Remember:\n- You are the final step in a multi-agent system
        \n- Your responses should be helpful and clear, but never speculative\n
        - Honesty about data limitations is crucial\n
        - When in doubt, state what data you have and what data you don't have\n\n
        
        Stay strictly within the bounds of:\n
        1. The user's original question\n
        2. The exact data provided\n
        3. General tRNA biology knowledge when appropriate\n\n
        
        Do not:\n
        - Generate example data\n
        - Make assumptions about missing data\n
        - Predict or extrapolate beyond the provided information\n
        - Create hypothetical scenarios with specific sequences

        IMPORTANT: do not include the actual data, but reference what you are talking about. The user also has the data already.
        Note that if tool output suggests to ask the user for more information, you should conversationally ask for the additional info needed.
               
        remember that our goal is to be conversational, not to just give boring responses. Its critically importatnt to stay grounded in factual reality, but you should chat like a professional trna researcher friend and collegue
               """

class ToolManager:
    def __init__(self, rna_central_tool, alignment_tool, trnascan_sprinzl_tool, tertiary_struct_tool, db_search_tool): # fix this gobbldy gook
        self.tools = {
            ToolType.GET_TRNA: self._create_rna_central_handler(rna_central_tool),
            ToolType.ALIGNER: self._create_alignment_handler(alignment_tool),
            ToolType.TRNASCAN_SPRINZL: self._create_trnascan_sprinzl_handler(trnascan_sprinzl_tool),
            ToolType.TERTIARY_STRUCT: self._create_tertiary_struct_handler(tertiary_struct_tool),
            ToolType.CHECK_DB: self. _create_dbsearch_handler(db_search_tool)
        }

    def _create_trnascan_sprinzl_handler(self, trnascan_sprinzl_tool):
        def handler(plan_response: str) -> ToolResult:
            result = trnascan_sprinzl_tool.parse_pipeline_request(plan_response)
            return ToolResult(
                tool_type=ToolType.TRNASCAN_SPRINZL,
                data=result,
                raw_output=str(result)
            )
        return handler
    
    def _create_tertiary_struct_handler(self, tertiary_struct_tool):
        def handler(plan_response: str) -> ToolResult:
            tertiary_struct_tool.use_tool(str(plan_response))
            return ToolResult(
                tool_type=ToolType.TERTIARY_STRUCT,
                data= "BLOCKS.txt atomic coord file SUCCESFULLY collected, (user has visualization tool on frontend). STEP IS COMPLETE, move to next step if applicable",
                raw_output=str("N/A, data is in the form of a file:  STEP IS COMPLETE, move to next step if applicable")
            )
        return handler


    def _create_rna_central_handler(self, rna_central_tool):
        def handler(plan_response: str) -> ToolResult:
            # Extract query parameters from plan_response if needed
            result = rna_central_tool.use_rna_central_tool(plan_response)
            return ToolResult(
                tool_type=ToolType.GET_TRNA,
                data=result,
                raw_output=str(result)
            )
        return handler
    
    def _create_alignment_handler(self, alignment_tool):
        def handler(plan_response: str) -> ToolResult:
            # Extract sequence IDs from plan_response if needed
            result = alignment_tool.use_tool(plan_response)
            return ToolResult(
                tool_type=ToolType.ALIGNER,
                data=result,
                raw_output=str(result)
            )
        return handler

    def _create_dbsearch_handler(self, db_search_tool):
        def handler(plan_response: str) -> ToolResult:
            # Extract sequence IDs from plan_response if needed
            result = db_search_tool.use_db_search_tool(plan_response)
            print("DB SEARCH HANGLER")
            print("plan: ", plan_response)
            print("result: ", result)
            return ToolResult(
                tool_type=ToolType.CHECK_DB,
                data=result,
                raw_output=str(result)
            )
        return handler

    def execute_tool(self, plan_response: str) -> Optional[ToolResult]:
        tool_type = self._identify_tool(plan_response)
        if not tool_type:
            return None
            
        return self.tools[tool_type](plan_response)
    
    def _identify_tool(self, plan_response: str) -> Optional[ToolType]:
        if "GET_TRNA" in plan_response:
            return ToolType.GET_TRNA
        elif "ALIGNER" in plan_response:
            return ToolType.ALIGNER
        elif "tRNAscan-SE/SPRINZL" in plan_response:
            return ToolType.TRNASCAN_SPRINZL
        elif "TERTIARY_STRUCT" in plan_response:
            return ToolType.TERTIARY_STRUCT
        elif "CHECK_DB" in plan_response:
            return ToolType.CHECK_DB
        return None

class TwoAgentChatbot:
    def __init__(self, sequence_cache=None):
        self.api_key=Config.ANTHROPIC_API_KEY
        
        self.user_facing_agent = UserFacingAgent(self.api_key)
        self.tool_manager = ToolManager(
            rna_central_tool=rnaCentralTool(sequence_cache),
            alignment_tool=BasicAlignmentTool(sequence_cache),
            trnascan_sprinzl_tool=RunPipeline(sequence_cache),
            tertiary_struct_tool=RNAFoldingTool(sequence_cache),
            db_search_tool=DBSearchTool(sequence_cache)
        ) # why is this so ugly- tools hsould be standatdized
    
    def process_query(self, user_input: str) -> str:
        accumulated_data: List[ToolResult] = []
        last_plan_response = None
        user_chat_history = "User input history: " + str(self.user_facing_agent.get_chat_history())
        
        i = 0
        while i < 6:
            # Get next step from planning agent
            self.planning_agent = PlanningAgent(self.api_key, user_chat_history)
            plan_response = self.planning_agent.get_next_step(
                user_input,
                accumulated_data,
                last_plan_response
            )
            
            # Check if planning is complete
            if "PLAN_COMPLETE=True" in plan_response:
                break
            elif "PLAN_FAILED=True" in plan_response:
                break # add handling for failed plan
                
            # Execute tool if specified in plan
            tool_result = self.tool_manager.execute_tool(plan_response)


            if tool_result:
                accumulated_data.append(tool_result)

            last_plan_response = plan_response
            i += 1
        
        # Generate final user-facing response
        print("response generated")
        return self.user_facing_agent.generate_response(user_input, accumulated_data)

if __name__ == "__main__":
    try:
        print("\nInitializing tRNA Analysis Chatbot...")
        chatbot = TwoAgentChatbot()
        print("\n=== tRNA Analysis Chatbot Ready ===")
        print("Type 'quit', 'exit', or press Ctrl+C to end the conversation")
        print("Enter your question about tRNA sequences below:")
        
        while True:
            # Print a prompt and get user input
            print("\n> ", end="")
            user_input = input().strip()
            
            # Check for exit commands
            if user_input.lower() in ['quit', 'exit']:
                print("\nThank you for using the tRNA Analysis Chatbot. Goodbye!")
                break
            
            # Skip empty inputs
            if not user_input:
                continue
            
            try:
                # Process the query and print the response
                print("\nProcessing your query...")
                response = chatbot.process_query(user_input)
                print("\nResponse:")
                print(response)
                
            except Exception as e:
                print(f"\nAn error occurred while processing your query: {str(e)}")
                print("Please try again or type 'exit' to quit.")
    
    except KeyboardInterrupt:
        print("\n\nChatbot terminated by user. Goodbye!")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")
    finally:
        # Cleanup?
        pass