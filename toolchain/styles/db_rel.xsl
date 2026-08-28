<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="text"/>
<!-- db.xsl -->
<!-- Copyright Terry Porter 2025, https://mecrisp-stellaris-folkdoc.sourceforge.io/index.html  -->
<!-- MIT Licensed -->

<xsl:template match="/device"> 

   
<!-- PERIPHERALS -->
<xsl:text>PRAGMA foreign_keys=OFF;</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>BEGIN TRANSACTION;</xsl:text>
  <xsl:text>&#10;</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>CREATE TABLE IF NOT EXISTS </xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>peripheral(</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>name TEXT PRIMARY KEY NOT NULL,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>description TEXT</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>);</xsl:text>
  <xsl:text>&#10;</xsl:text>

<xsl:for-each select="peripherals/peripheral">
<xsl:variable name="peripheral_name" select="name" />
<xsl:text>INSERT INTO </xsl:text>
<xsl:text>peripheral</xsl:text>
<xsl:text> VALUES(</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="description"/><xsl:text>');</xsl:text>
  <xsl:text>&#10;</xsl:text>
  <xsl:text>&#10;</xsl:text>


<!-- REGISTERS -->
<xsl:text>CREATE TABLE IF NOT EXISTS </xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>register(</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>peripheral_name TEXT NOT NULL,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>name TEXT NOT NULL,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>address TEXT,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>resetValue TEXT,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>access TEXT,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>description TEXT,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>PRIMARY KEY (peripheral_name, name)</xsl:text>
<xsl:text>);</xsl:text>
  <xsl:text>&#10;</xsl:text>
  <xsl:text>&#10;</xsl:text>

<xsl:for-each select="registers/register">
<xsl:variable name="register_name" select="name" />
<xsl:text>INSERT INTO </xsl:text>
<xsl:text>register</xsl:text>
<xsl:text> VALUES(</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="$peripheral_name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="address"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="resetValue"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="access"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="description"/><xsl:text>');</xsl:text>
  <xsl:text>&#10;</xsl:text>
  <xsl:text>&#10;</xsl:text>


<!-- FIELDS -->
<xsl:text>CREATE TABLE IF NOT EXISTS </xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>field(</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>peripheral_name TEXT NOT NULL,</xsl:text>
<xsl:text>register_name TEXT NOT NULL,</xsl:text>
<xsl:text>name TEXT NOT NULL,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>bitWidth NUMERIC,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>bitOffset NUMERIC,</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>description TEXT</xsl:text>
  <xsl:text>&#10;</xsl:text>
<xsl:text>);</xsl:text>
  <xsl:text>&#10;</xsl:text>


<xsl:for-each select="fields/field">
<xsl:text>INSERT INTO </xsl:text>
<xsl:text>field</xsl:text>
<xsl:text> VALUES(</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="$peripheral_name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="$register_name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="name"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="bitWidth"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="bitOffset"/><xsl:text>',</xsl:text>
<xsl:text>'</xsl:text><xsl:value-of select="description"/><xsl:text>');</xsl:text>
  <xsl:text>&#10;</xsl:text>
  <xsl:text>&#10;</xsl:text>





</xsl:for-each>
</xsl:for-each>
</xsl:for-each>

<xsl:text>&#10;</xsl:text>
<xsl:text>COMMIT;</xsl:text>
</xsl:template>
</xsl:stylesheet>
