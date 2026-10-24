// Minimal JSON parser/writer helpers (no external deps).
#pragma once
#include <string>
#include <vector>
#include <utility>
#include <cstdlib>
#include <cstdio>
#include <stdexcept>

struct JVal {
  enum T { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
  double n = 0; bool b = false; std::string s;
  std::vector<JVal> a; std::vector<std::pair<std::string, JVal>> o;
  const JVal* get(const std::string& k) const {
    if (t != OBJ) return nullptr;
    for (auto& p : o) if (p.first == k) return &p.second;
    return nullptr;
  }
};

struct JParser {
  const char* p; const char* e;
  JParser(const std::string& s) : p(s.data()), e(s.data() + s.size()) {}
  void ws() { while (p < e && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) p++; }
  [[noreturn]] void fail(const char* m) { throw std::runtime_error(m); }
  JVal parse() { ws(); JVal v = val(); return v; }
  std::string str() {
    if (p >= e || *p != '"') fail("expected string");
    p++; std::string out;
    while (p < e && *p != '"') {
      if (*p == '\\') {
        p++; if (p >= e) fail("bad escape");
        char c = *p++;
        switch (c) {
          case 'n': out += '\n'; break; case 't': out += '\t'; break; case 'r': out += '\r'; break;
          case 'b': out += '\b'; break; case 'f': out += '\f'; break;
          case 'u': {
            if (e - p < 4) fail("bad \\u");
            unsigned cp = strtoul(std::string(p, p + 4).c_str(), nullptr, 16); p += 4;
            if (cp < 0x80) out += (char)cp;
            else if (cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
            else { out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
            break;
          }
          default: out += c;
        }
      } else out += *p++;
    }
    if (p >= e) fail("unterminated string");
    p++; return out;
  }
  JVal val() {
    ws(); if (p >= e) fail("eof");
    JVal v;
    if (*p == '{') {
      v.t = JVal::OBJ; p++; ws();
      if (p < e && *p == '}') { p++; return v; }
      while (true) {
        ws(); std::string k = str(); ws();
        if (p >= e || *p != ':') fail("expected :"); p++;
        JVal x = val(); v.o.emplace_back(std::move(k), std::move(x)); ws();
        if (p < e && *p == ',') { p++; continue; }
        if (p < e && *p == '}') { p++; break; }
        fail("expected , or }");
      }
    } else if (*p == '[') {
      v.t = JVal::ARR; p++; ws();
      if (p < e && *p == ']') { p++; return v; }
      while (true) {
        v.a.push_back(val()); ws();
        if (p < e && *p == ',') { p++; continue; }
        if (p < e && *p == ']') { p++; break; }
        fail("expected , or ]");
      }
    } else if (*p == '"') { v.t = JVal::STR; v.s = str(); }
    else if (*p == 't') { if (e - p < 4) fail("bad"); p += 4; v.t = JVal::BOOL; v.b = true; }
    else if (*p == 'f') { if (e - p < 5) fail("bad"); p += 5; v.t = JVal::BOOL; v.b = false; }
    else if (*p == 'n') { if (e - p < 4) fail("bad"); p += 4; v.t = JVal::NUL; }
    else {
      char* end; v.n = strtod(p, &end); if (end == p) fail("bad number"); p = end; v.t = JVal::NUM;
    }
    return v;
  }
};

inline std::string jesc(const std::string& s) {
  std::string o = "\"";
  for (char c : s) { if (c == '"' || c == '\\') { o += '\\'; o += c; } else if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, 8, "\\u%04x", c); o += b; } else o += c; }
  return o + "\"";
}
