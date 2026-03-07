import { Schema, type, MapSchema, ArraySchema } from "@colyseus/schema";

export class AgentSchema extends Schema {
  @type("string") id: string = "";
  @type("string") name: string = "";
  @type("string") role: string = "";
  @type("string") status: string = "idle";
  @type("number") level: number = 1;
  @type("number") x: number = 0;
  @type("number") y: number = 0;
  @type(["string"]) skills = new ArraySchema<string>();
}

export class DepartmentSchema extends Schema {
  @type("string") id: string = "";
  @type("string") name: string = "";
  @type("string") slug: string = "";
  @type("number") maxAgents: number = 4;
  @type("number") x: number = 0;
  @type("number") y: number = 0;
  @type([AgentSchema]) agents: ArraySchema<AgentSchema> =
    new ArraySchema<AgentSchema>();
}

export class TacticianSchema extends Schema {
  @type("string") sessionId: string = "";
  @type("string") name: string = "";
  @type("number") x: number = 400;
  @type("number") y: number = 300;
  @type("string") direction: string = "down";
}

export class ChatMessageSchema extends Schema {
  @type("string") id: string = "";
  @type("string") senderSessionId: string = "";
  @type("string") senderName: string = "";
  @type("string") content: string = "";
  @type("number") timestamp: number = 0;
  @type("boolean") isSystem: boolean = false;
}

export class OfficeStateSchema extends Schema {
  @type({ map: DepartmentSchema }) departments: MapSchema<DepartmentSchema> =
    new MapSchema<DepartmentSchema>();
  @type({ map: TacticianSchema }) players: MapSchema<TacticianSchema> =
    new MapSchema<TacticianSchema>();
  @type([ChatMessageSchema]) chatMessages: ArraySchema<ChatMessageSchema> =
    new ArraySchema<ChatMessageSchema>();
  @type("number") pendingApprovalCount: number = 0;
}
