CREATE CONSTRAINT `call_id` FOR (n:`Call`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `command_template` FOR (n:`Command`) REQUIRE (n.`template`) IS UNIQUE;
CREATE CONSTRAINT `errorsig_sig` FOR (n:`ErrorSig`) REQUIRE (n.`sig`) IS UNIQUE;
CREATE CONSTRAINT `session_id` FOR (n:`Session`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `source_name` FOR (n:`Source`) REQUIRE (n.`name`) IS UNIQUE;
