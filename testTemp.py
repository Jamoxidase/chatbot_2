from tools.rnaComprnaoser import RNAFoldingTool

if __name__ == "__main__":
    tool = RNAFoldingTool()
    #only works if sequence is already in cache
    test = tool.use_tool(" random text RNAcentral ID: URS0000C8E9CE_9606")

