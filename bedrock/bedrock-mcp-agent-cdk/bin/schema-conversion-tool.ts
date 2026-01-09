import * as path from 'path';
import * as fs from 'fs';
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport, StdioServerParameters } from "@modelcontextprotocol/sdk/client/stdio.js";

interface SchemaProperty {
  type: string;
  description?: string;
  enum?: any[];
  default?: any;
  items?: any;
  properties?: Record<string, SchemaProperty>;
  required?: string[];
  [key: string]: any;  // 기타 가능한 속성들을 위한 인덱스 시그니처
}

export interface InputSchema {
  type: string;
  properties: Record<string, SchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
  [key: string]: any;
}

export interface Tool {
  name: string;
  description: string;
  inputSchema: InputSchema;
  [key: string]: any;
}

interface ToolsResponse {
  tools: Tool[];
}

export interface OpenAPISpec {
  openapi: string;
  info: {
    title: string;
    version: string;
    description?: string;
  };
  paths: Record<string, any>;
  // components: {
  //   schemas: Record<string, any>;
  // };
}

interface McpServerConfig {
  command: string;
  args: string[];
  bundling?: any
}

interface McpConfig {
  mcpServers: {
      [key: string]: McpServerConfig;
  };
}

export function convertToOpenAPI(mcpName: String, toolsJson: ToolsResponse): any {
  const openapi: OpenAPISpec = {
    openapi: '3.0.0',
    info: {
      title: mcpName + ' API',
      version: '1.0.0'
    },
    paths: {},
    // components: {
    //   schemas: {}
    // }
  };

  // 스키마 복사를 위한 헬퍼 함수
  function deepCloneSchema(schema: any): any {
    if (Array.isArray(schema)) {
      return schema.map(item => deepCloneSchema(item));
    }
    if (typeof schema === 'object' && schema !== null) {
      const cloned: any = {};
      for (const [key, value] of Object.entries(schema)) {
        cloned[key] = deepCloneSchema(value);
      }
      return cloned;
    }
    return schema;
  }

  function cleanObject(obj: InputSchema): InputSchema {
    const allowedKeys = ['type', 'properties', 'required', 'additionalProperties'];
    const cleanedObject = Object.keys(obj)
        .filter(key => allowedKeys.includes(key))
        .reduce((acc, key) => ({
            ...acc,
            [key]: obj[key]
        }), {} as InputSchema);
    
    return cleanedObject;
  }

  try {
    toolsJson.tools.forEach(tool => {
      try {
        const pathName = `/${tool.name}`;
        
        // 요청 스키마 생성
        const requestSchema = deepCloneSchema(cleanObject(tool.inputSchema));

        // 경로 항목 생성
        openapi.paths[pathName] = {
          post: {
            tags: ['tools'],
            summary: tool.description,
            description: tool.description,
            operationId: tool.name,
            requestBody: {
              required: true,
              content: {
                'application/json': {
                  schema: requestSchema
                }
              }
            },
            responses: {
              '200': {
                description: 'Successful operation',
                content: {
                  'application/json': {
                    schema: {
                      type: 'object',
                      properties: {
                        result: {
                          type: 'object',
                          description: 'The operation result',
                          additionalProperties: true
                        }
                      }
                    }
                  }
                }
              },
              '400': {
                description: 'Bad request',
                content: {
                  'application/json': {
                    schema: {
                      type: 'object',
                      properties: {
                        error: {
                          type: 'string',
                          description: 'Error message',
                          additionalProperties: true
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        };
      } catch (error) {
        console.error(`Error processing tool ${tool.name}:`, error);
      }
    });
  } catch (error) {
    console.error('Error processing tools:', error);
  }

  return openapi;
}

async function main() {
  try {
    const mcpConfigPath = path.join(__dirname, '../conf/mcp.json');
    console.log(mcpConfigPath);

    const mcpConfig = JSON.parse(fs.readFileSync(mcpConfigPath, 'utf8'));
    let openApiSchema: any = {};

    for (const [mcpServerName, mcpServerConfig] of Object.entries(mcpConfig.mcpServers)) {
      console.log("Converting MCP tools to OpenAPI schema: " + mcpServerName);
      const command = (mcpServerConfig as McpServerConfig).command;
      const args = (mcpServerConfig as McpServerConfig).args;

      const transport = new StdioClientTransport({
        command: command,
        args: args
      });
      
      const client = new Client(
        {
          name: "bedrock-agent-client",
          version: "0.0.1"
        },
        {
          capabilities: {
            tools: {}
          }
        }
      );

      await client.connect(transport);
      const serverCapabilities = client.getServerCapabilities()

      if(serverCapabilities && 'tools' in serverCapabilities){
        const tools = await client.listTools();
        openApiSchema[mcpServerName] = convertToOpenAPI(mcpServerName, tools as ToolsResponse)
      }
      await client.close();
    }

    fs.writeFileSync(path.join(__dirname, '../conf/generated_open_api_schema.json'), JSON.stringify(openApiSchema, null, 2), 'utf8');
  }
  catch (error) {
    console.error("Schema conversion tool error:", error);
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error("Unhandled error:", error);
    process.exit(1);
  });
}